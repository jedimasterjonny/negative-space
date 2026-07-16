from __future__ import annotations

import datetime
import io
import struct
from typing import TYPE_CHECKING

import pytest
from PIL import Image

from negative_space.exif import (
    Capture,
    _find_box,
    _mvhd_creation,
    _parse_datetime,
    _parse_gps,
    _select_datetime,
    _to_decimal,
    content_extension,
    read_capture,
)

if TYPE_CHECKING:
    from pathlib import Path

_EPOCH_1904 = datetime.datetime(1904, 1, 1, tzinfo=datetime.UTC)


# --- pure helpers ----------------------------------------------------------


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("2019:09:27 11:47:23", datetime.datetime(2019, 9, 27, 11, 47, 23)),  # noqa: DTZ001
        ("  2019:09:27 11:47:23  ", datetime.datetime(2019, 9, 27, 11, 47, 23)),  # noqa: DTZ001
        ("0000:00:00 00:00:00", None),  # blank
        ("garbage", None),
        (12345, None),  # not a string
        (None, None),
    ],
)
def test_parse_datetime(raw: object, expected: datetime.datetime | None) -> None:
    assert _parse_datetime(raw) == expected


def test_select_datetime_prefers_original_then_digitized_then_base() -> None:
    assert _select_datetime({0x9003: "orig"}, "base") == "orig"
    assert _select_datetime({0x9004: "digi"}, "base") == "digi"
    assert _select_datetime({}, "base") == "base"


@pytest.mark.parametrize(
    ("dms", "ref", "expected"),
    [
        ((51, 30, 0), "N", 51.5),
        ((0, 7, 30), "W", -0.125),  # west is negative
        ((51, 30), "N", None),  # not a triple
        ("nope", "N", None),  # not a sequence
        ((51, 30, "x"), "N", None),  # non-numeric part
    ],
)
def test_to_decimal(dms: object, ref: str, expected: float | None) -> None:
    result = _to_decimal(dms, ref)
    if expected is None:
        assert result is None
    else:
        assert result == pytest.approx(expected)


def test_parse_gps() -> None:
    gps = {1: "N", 2: (51, 30, 0), 3: "W", 4: (0, 7, 30)}
    latitude, longitude = _parse_gps(gps)
    assert latitude == pytest.approx(51.5)
    assert longitude == pytest.approx(-0.125)
    assert _parse_gps({}) == (None, None)


# --- MP4 box parsing -------------------------------------------------------


def _box(box_type: bytes, body: bytes) -> bytes:
    return struct.pack(">I", 8 + len(body)) + box_type + body


def _mvhd_body(created: int, version: int = 0) -> bytes:
    header = bytes([version, 0, 0, 0])  # version + 3 flag bytes
    stamp = struct.pack(">Q", created) if version == 1 else struct.pack(">I", created)
    return header + stamp + b"\x00" * 16  # remaining mvhd fields (unused here)


def _mp4(created: int, version: int = 0) -> bytes:
    moov = _box(b"moov", _box(b"mvhd", _mvhd_body(created, version)))
    return _box(b"ftyp", b"isom\x00\x00\x00\x00") + moov


def _seconds_since_1904(dt: datetime.datetime) -> int:
    return int((dt - _EPOCH_1904).total_seconds())


def test_find_box_skips_64bit_and_finds_target() -> None:
    body = b"isom"
    ftyp = struct.pack(">I", 1) + b"ftyp" + struct.pack(">Q", 16 + len(body)) + body
    data = ftyp + _box(b"moov", b"")
    assert _find_box(io.BytesIO(data), b"moov", len(data)) is not None


def test_find_box_size_zero_runs_to_end() -> None:
    data = struct.pack(">I", 0) + b"moov" + b"payload"
    assert _find_box(io.BytesIO(data), b"moov", len(data)) == (0, len(data), 8)


def test_find_box_not_found_and_short_header() -> None:
    only_ftyp = _box(b"ftyp", b"")
    assert _find_box(io.BytesIO(only_ftyp), b"moov", len(only_ftyp)) is None
    assert _find_box(io.BytesIO(b"\x00\x00"), b"moov", 2) is None


def test_mvhd_creation_version_0_and_1() -> None:
    seconds = _seconds_since_1904(datetime.datetime(2020, 6, 15, 12, tzinfo=datetime.UTC))
    assert _mvhd_creation(io.BytesIO(_mp4(seconds))) == seconds
    assert _mvhd_creation(io.BytesIO(_mp4(seconds, version=1))) == seconds


def test_mvhd_creation_missing_boxes() -> None:
    assert _mvhd_creation(io.BytesIO(_box(b"ftyp", b""))) is None  # no moov
    assert _mvhd_creation(io.BytesIO(_box(b"moov", _box(b"free", b"")))) is None  # no mvhd


# --- read_capture end to end ----------------------------------------------


def _jpeg_with_datetime(path: Path, taken: str) -> None:
    image = Image.new("RGB", (2, 2), (200, 50, 50))
    exif = image.getexif()
    exif[0x0132] = taken  # DateTime in the base IFD
    image.save(path, exif=exif)


def test_read_capture_image_with_exif_date(tmp_path: Path) -> None:
    path = tmp_path / "photo.jpg"
    _jpeg_with_datetime(path, "2019:09:27 11:47:23")

    assert read_capture(path) == Capture(taken_at=datetime.datetime(2019, 9, 27, 11, 47, 23))  # noqa: DTZ001


def test_read_capture_image_without_date(tmp_path: Path) -> None:
    path = tmp_path / "plain.jpg"
    Image.new("RGB", (2, 2)).save(path)

    assert read_capture(path) is None


def test_read_capture_corrupt_image(tmp_path: Path) -> None:
    path = tmp_path / "broken.jpg"
    path.write_bytes(b"not really a jpeg")

    assert read_capture(path) is None


def test_read_capture_video(tmp_path: Path) -> None:
    taken = datetime.datetime(2023, 8, 19, 11, 2, 58, tzinfo=datetime.UTC)
    path = tmp_path / "clip.mp4"
    path.write_bytes(_mp4(_seconds_since_1904(taken)))

    assert read_capture(path) == Capture(taken_at=taken.replace(tzinfo=None))


def test_read_capture_video_blank_and_implausible(tmp_path: Path) -> None:
    blank = tmp_path / "blank.mp4"
    blank.write_bytes(_mp4(0))
    assert read_capture(blank) is None  # creation_time 0

    old = tmp_path / "old.mp4"
    old.write_bytes(_mp4(100))  # 1904 -> implausible
    assert read_capture(old) is None


def test_read_capture_video_missing_file(tmp_path: Path) -> None:
    assert read_capture(tmp_path / "missing.mp4") is None  # open() raises -> None


def test_read_capture_unknown_type(tmp_path: Path) -> None:
    path = tmp_path / "notes.txt"
    path.write_text("hello")

    assert read_capture(path) is None


# --- content_extension -----------------------------------------------------


@pytest.mark.parametrize(
    ("head", "expected"),
    [
        (b"\xff\xd8\xff\xe0" + b"\x00" * 8, ".jpg"),
        (b"\x89PNG\r\n\x1a\n" + b"\x00" * 4, ".png"),
        (b"GIF89a" + b"\x00" * 6, ".gif"),
        (b"RIFF\x00\x00\x00\x00WEBP", ".webp"),
        (b"II*\x00" + b"\x00" * 8, ".tiff"),
        (b"\x00\x00\x00\x18ftypheic", ".heic"),
        (b"\x00\x00\x00\x18ftypmif1", ".heic"),
        (b"\x00\x00\x00\x18ftypavif", ".avif"),
        (b"\x00\x00\x00\x18ftypisom", None),  # an MP4 container, not an image
        (b"not an image", None),
    ],
)
def test_content_extension_sniffs_magic_bytes(
    tmp_path: Path, head: bytes, expected: str | None
) -> None:
    path = tmp_path / "file.bin"
    path.write_bytes(head)

    assert content_extension(path) == expected


def test_content_extension_missing_file(tmp_path: Path) -> None:
    assert content_extension(tmp_path / "gone.bin") is None
