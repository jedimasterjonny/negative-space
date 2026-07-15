"""Resolve each keeper's metadata down a source ladder.

For every media file we keep, find its capture time, GPS, people and caption
from the best available source, in order:

1. its own Takeout sidecar (``photoTakenTime`` etc.);
2. the sidecar of the original it is an edit of (inherited);
3. the file's own EXIF / MP4 metadata (date, and GPS for images);
4. nothing -- an undated straggler.

Each result is tagged with the :class:`MetadataSource` it came from, so the run
can be audited.
"""

from __future__ import annotations

import datetime
import enum
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Callable, Mapping

    from negative_space.exif import Capture
    from negative_space.pairing import DirectoryPairing, MediaEntry


class MetadataSource(enum.Enum):
    """Where a file's resolved metadata came from."""

    SIDECAR = "sidecar"
    INHERITED = "inherited"
    EXIF = "exif"
    UNRESOLVED = "unresolved"


@dataclass(frozen=True, slots=True)
class PhotoMetadata:
    """The metadata we care about for one media file."""

    taken_at: datetime.datetime | None
    latitude: float | None = None
    longitude: float | None = None
    people: tuple[str, ...] = field(default_factory=tuple)
    description: str = ""


@dataclass(frozen=True, slots=True)
class Resolved:
    """One keeper's metadata plus where it was resolved from."""

    name: str
    metadata: PhotoMetadata
    source: MetadataSource
    via: str | None = None  # the original file, when ``source`` is INHERITED

    @property
    def has_date(self) -> bool:
        """Whether a capture date was found."""
        return self.metadata.taken_at is not None


def _timestamp(node: object) -> datetime.datetime | None:
    if not isinstance(node, dict):
        return None
    raw = node.get("timestamp")
    if not isinstance(raw, str | int):
        return None
    try:
        return datetime.datetime.fromtimestamp(int(raw), tz=datetime.UTC)
    except ValueError:
        return None


def _coord(node: object) -> tuple[float, float] | None:
    if not isinstance(node, dict):
        return None
    latitude, longitude = node.get("latitude"), node.get("longitude")
    if not (isinstance(latitude, int | float) and isinstance(longitude, int | float)):
        return None
    if not (latitude or longitude):  # Takeout writes 0.0 / 0.0 when there is no fix
        return None
    return float(latitude), float(longitude)


def _people(node: object) -> tuple[str, ...]:
    if not isinstance(node, list):
        return ()
    names: list[str] = []
    for person in node:
        if isinstance(person, dict):
            name = person.get("name")
            if isinstance(name, str):
                names.append(name)
    return tuple(names)


def parse_sidecar(data: Mapping[str, object]) -> PhotoMetadata:
    """Parse a Takeout sidecar's JSON into :class:`PhotoMetadata`.

    Args:
        data: The decoded sidecar JSON.

    Returns:
        The metadata, preferring ``geoData`` GPS over ``geoDataExif``.
    """
    coords = _coord(data.get("geoData")) or _coord(data.get("geoDataExif"))
    description = data.get("description")
    return PhotoMetadata(
        taken_at=_timestamp(data.get("photoTakenTime")),
        latitude=coords[0] if coords else None,
        longitude=coords[1] if coords else None,
        people=_people(data.get("people")),
        description=description.strip() if isinstance(description, str) else "",
    )


def _resolve(
    entry: MediaEntry,
    by_name: Mapping[str, MediaEntry],
    load_sidecar: Callable[[str], Mapping[str, object] | None],
    read_exif: Callable[[str], Capture | None],
) -> Resolved:
    if entry.sidecar:
        data = load_sidecar(entry.sidecar)
        if data is not None:
            return Resolved(entry.name, parse_sidecar(data), MetadataSource.SIDECAR)

    parent = by_name.get(entry.original) if entry.original else None
    if parent is not None and parent.sidecar:
        data = load_sidecar(parent.sidecar)
        if data is not None:
            metadata = parse_sidecar(data)
            return Resolved(entry.name, metadata, MetadataSource.INHERITED, via=parent.name)

    capture = read_exif(entry.name)
    if capture is not None:
        metadata = PhotoMetadata(capture.taken_at, capture.latitude, capture.longitude)
        return Resolved(entry.name, metadata, MetadataSource.EXIF)

    return Resolved(entry.name, PhotoMetadata(taken_at=None), MetadataSource.UNRESOLVED)


def resolve_directory(
    pairing: DirectoryPairing,
    *,
    load_sidecar: Callable[[str], Mapping[str, object] | None],
    read_exif: Callable[[str], Capture | None],
) -> list[Resolved]:
    """Resolve metadata for every keeper in a folder.

    Args:
        pairing: The folder's pairing (keepers, sidecars, edit links).
        load_sidecar: Reads a sidecar JSON by file name.
        read_exif: Reads embedded EXIF/MP4 capture info by media file name.

    Returns:
        One :class:`Resolved` per keeper, tagged with its metadata source.
    """
    by_name = {entry.name: entry for entry in pairing.entries}
    return [_resolve(entry, by_name, load_sidecar, read_exif) for entry in pairing.keepers]
