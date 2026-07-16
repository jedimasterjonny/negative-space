"""Read a capture date (and GPS) straight from a media file.

A last-resort backup for the few takeout files that have no sidecar and are not
an edit of another file. Images are read with Pillow's EXIF; videos are read
from the MP4/MOV ``mvhd`` box with a small pure-Python parse -- Pillow cannot
read video metadata, and this keeps us off heavier tools like ffprobe.
"""

from __future__ import annotations

import datetime
import struct
from dataclasses import dataclass
from typing import TYPE_CHECKING, BinaryIO, Final, SupportsFloat

from PIL import Image, UnidentifiedImageError

from negative_space.pairing import is_image, is_video

if TYPE_CHECKING:
    from collections.abc import Mapping
    from pathlib import Path

# HEIF/AVIF brands that follow the ``ftyp`` box at bytes 4:8. Google Takeout
# stores many iPhone photos as JPEG bytes under a ``.HEIC`` name, so the true
# content -- not the extension -- must drive the output name and the rewrite.
_HEIF_BRANDS: Final = frozenset(
    {
        b"heic",
        b"heix",
        b"heim",
        b"heis",
        b"hevc",
        b"hevx",
        b"hevm",
        b"hevs",
        b"mif1",
        b"msf1",
        b"mif2",
    }
)
_AVIF_BRANDS: Final = frozenset({b"avif", b"avis"})
_MAGIC_BYTES: Final = 12
# Formats identified by a fixed leading signature (the ftyp-based ones are below).
_SIGNATURES: Final = (
    (b"\xff\xd8\xff", ".jpg"),
    (b"\x89PNG\r\n\x1a\n", ".png"),
    (b"GIF87a", ".gif"),
    (b"GIF89a", ".gif"),
    (b"II*\x00", ".tiff"),
    (b"MM\x00*", ".tiff"),
)

_EXIF_IFD: Final = 0x8769
_GPS_IFD: Final = 0x8825
# GPS sub-IFD tags: latitude/longitude as (deg, min, sec) plus an N/S/E/W ref.
_GPS_LAT_REF: Final = 1
_GPS_LAT: Final = 2
_GPS_LNG_REF: Final = 3
_GPS_LNG: Final = 4
_DATETIME_TAGS: Final = (0x9003, 0x9004)  # DateTimeOriginal, DateTimeDigitized
_BASE_DATETIME: Final = 0x0132
_EXIF_DT_FORMAT: Final = "%Y:%m:%d %H:%M:%S"

# MP4/QuickTime timestamps count seconds from 1904-01-01 UTC.
_MP4_EPOCH: Final = datetime.datetime(1904, 1, 1, tzinfo=datetime.UTC)
_PLAUSIBLE_YEARS: Final = range(1995, 2101)
_BOX_HEADER: Final = 8


@dataclass(frozen=True, slots=True)
class Capture:
    """A capture date recovered from a file's embedded metadata."""

    taken_at: datetime.datetime
    latitude: float | None = None
    longitude: float | None = None


def read_capture(path: Path) -> Capture | None:
    """Return the capture date embedded in ``path``, or ``None``.

    Args:
        path: A media file.

    Returns:
        The recovered capture (with GPS for images that carry it), or ``None``
        when the file is not a supported type or has no usable date.
    """
    if is_image(path.name):
        return _read_image(path)
    if is_video(path.name):
        return _read_video(path)
    return None


def content_extension(path: Path) -> str | None:
    """Return the canonical extension for a file's real content, or ``None``.

    Identifies the type from the leading magic bytes rather than trusting the
    name, so a JPEG mislabelled ``.HEIC`` is named -- and rewritten -- as a JPEG.

    Args:
        path: A file to sniff.

    Returns:
        A lower-case extension including the dot (e.g. ``".jpg"``), or ``None``
        when the content is not a recognised image type.
    """
    try:
        with path.open("rb") as stream:
            head = stream.read(_MAGIC_BYTES)
    except OSError:
        return None
    for signature, extension in _SIGNATURES:
        if head.startswith(signature):
            return extension
    if head[:4] == b"RIFF" and head[8:12] == b"WEBP":
        return ".webp"
    if head[4:8] == b"ftyp":
        brand = head[8:12]
        if brand in _AVIF_BRANDS:
            return ".avif"
        if brand in _HEIF_BRANDS:
            return ".heic"
    return None


def _parse_datetime(raw: object) -> datetime.datetime | None:
    if not isinstance(raw, str):
        return None
    try:
        return datetime.datetime.strptime(raw.strip(), _EXIF_DT_FORMAT)  # noqa: DTZ007
    except ValueError:
        return None  # blank ("0000:00:00 ...") or malformed


def _select_datetime(exif_ifd: Mapping[int, object], base: object) -> object:
    for tag in _DATETIME_TAGS:
        if tag in exif_ifd:
            return exif_ifd[tag]
    return base


def _to_decimal(dms: object, ref: object) -> float | None:
    if not isinstance(dms, tuple | list) or len(dms) != 3:  # noqa: PLR2004 - deg/min/sec
        return None
    parts: list[float] = []
    for part in dms:
        if not isinstance(part, SupportsFloat):
            return None
        parts.append(float(part))
    degrees, minutes, seconds = parts
    value = degrees + minutes / 60 + seconds / 3600
    return -value if ref in {"S", "W"} else value


def _parse_gps(gps: Mapping[int, object]) -> tuple[float | None, float | None]:
    latitude = longitude = None
    if _GPS_LAT in gps and _GPS_LAT_REF in gps:
        latitude = _to_decimal(gps[_GPS_LAT], gps[_GPS_LAT_REF])
    if _GPS_LNG in gps and _GPS_LNG_REF in gps:
        longitude = _to_decimal(gps[_GPS_LNG], gps[_GPS_LNG_REF])
    return latitude, longitude


def _read_image(path: Path) -> Capture | None:
    try:
        with Image.open(path) as image:
            exif = image.getexif()
            raw = _select_datetime(exif.get_ifd(_EXIF_IFD), exif.get(_BASE_DATETIME))
            gps = dict(exif.get_ifd(_GPS_IFD))
    except (OSError, UnidentifiedImageError, SyntaxError):
        return None
    taken_at = _parse_datetime(raw)
    if taken_at is None:
        return None
    latitude, longitude = _parse_gps(gps)
    return Capture(taken_at=taken_at, latitude=latitude, longitude=longitude)


def _find_box(stream: BinaryIO, target: bytes, end: int) -> tuple[int, int, int] | None:
    while stream.tell() < end:
        start = stream.tell()
        header = stream.read(_BOX_HEADER)
        if len(header) < _BOX_HEADER:
            return None
        size = struct.unpack(">I", header[:4])[0]
        header_len = _BOX_HEADER
        if size == 1:  # 64-bit extended size follows the header
            size = struct.unpack(">Q", stream.read(8))[0]
            header_len = 16
        elif size == 0:  # box runs to the end of the file
            size = end - start
        if header[4:8] == target:
            return start, size, header_len
        stream.seek(start + size)
    return None


def _mvhd_creation(stream: BinaryIO) -> int | None:
    stream.seek(0, 2)
    end = stream.tell()
    stream.seek(0)
    moov = _find_box(stream, b"moov", end)
    if moov is None:
        return None
    stream.seek(moov[0] + moov[2])
    mvhd = _find_box(stream, b"mvhd", moov[0] + moov[1])
    if mvhd is None:
        return None
    stream.seek(mvhd[0] + mvhd[2])
    version = stream.read(4)[0]  # 1-byte version + 3-byte flags
    width = 8 if version == 1 else 4
    return struct.unpack(">Q" if version == 1 else ">I", stream.read(width))[0]


def _read_video(path: Path) -> Capture | None:
    try:
        with path.open("rb") as stream:
            created = _mvhd_creation(stream)
    except (OSError, struct.error, IndexError):
        return None
    if not created:
        return None
    taken_at = (_MP4_EPOCH + datetime.timedelta(seconds=created)).replace(tzinfo=None)
    if taken_at.year not in _PLAUSIBLE_YEARS:
        return None
    return Capture(taken_at=taken_at)
