"""Scan a paired, resolved takeout and build a read-only organise plan.

Walking + reading sidecars happens here (over the NFS mount); nothing is
modified. The result is a :class:`LibraryPlan` -- where every kept file would
move and which motion videos would be dropped -- plus a :class:`PlanSummary`
for the audit report.
"""

from __future__ import annotations

import json
import os
from collections import Counter
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING

from negative_space.exif import content_extension, read_capture
from negative_space.metadata import resolve_directory
from negative_space.organise import UNSORTED, PlanItem, plan_moves
from negative_space.pairing import pair_directory

if TYPE_CHECKING:
    from collections.abc import Iterable, Mapping
    from pathlib import PurePosixPath

    from negative_space.metadata import MetadataSource, PhotoMetadata


@dataclass(frozen=True, slots=True)
class Keeper:
    """A media file to keep, with its resolved metadata, size and true extension."""

    source: Path
    is_video: bool
    size: int
    extension: str  # from content, not the (sometimes wrong) name, e.g. ".jpg"
    metadata: PhotoMetadata
    source_tag: MetadataSource


@dataclass(frozen=True, slots=True)
class Drop:
    """A motion-photo video to delete, with its size."""

    source: Path
    size: int


@dataclass(frozen=True, slots=True)
class Duplicate:
    """A redundant copy of a kept file (same name and size in another album)."""

    source: Path
    size: int
    kept: Path  # the copy being kept; apply verifies ``source`` is byte-identical to it


@dataclass(frozen=True, slots=True)
class Placement:
    """Where a kept file will move to."""

    source: Path
    destination: PurePosixPath  # relative to the organised library root
    is_video: bool
    metadata: PhotoMetadata
    source_tag: MetadataSource


@dataclass(frozen=True, slots=True)
class LibraryPlan:
    """The whole planned reorganisation."""

    placements: tuple[Placement, ...]
    motion_drops: tuple[Drop, ...]
    duplicate_drops: tuple[Duplicate, ...]


@dataclass(frozen=True, slots=True)
class PlanSummary:
    """Aggregate counts for the audit report."""

    keepers: int
    photos: int
    videos: int
    undated: int
    by_source: dict[str, int]
    by_year: dict[int, int]
    motion_count: int
    motion_bytes: int
    duplicate_count: int
    duplicate_bytes: int


def _dedupe(keepers: list[Keeper]) -> tuple[list[Keeper], list[Duplicate]]:
    # Album-duplicates share a name and size across folders; keep one per group.
    kept_by_key: dict[tuple[str, int], Keeper] = {}
    unique: list[Keeper] = []
    duplicates: list[Duplicate] = []
    for keeper in sorted(keepers, key=lambda item: str(item.source)):  # deterministic winner
        key = (keeper.source.name, keeper.size)
        winner = kept_by_key.get(key)
        if winner is None:
            kept_by_key[key] = keeper
            unique.append(keeper)
        else:
            duplicates.append(Duplicate(keeper.source, keeper.size, winner.source))
    return unique, duplicates


def build_plan(keepers: Iterable[Keeper], motion: Iterable[Drop]) -> LibraryPlan:
    """Deduplicate keepers, assign destinations, and collect the drops.

    Album-duplicates (same name and size in more than one album) are reduced to
    one copy; the rest become :class:`Duplicate` drops for the apply step to
    hash-verify before deleting.

    Args:
        keepers: Media files to keep, with resolved metadata and sizes.
        motion: Motion-photo videos to delete.

    Returns:
        The library plan: collision-free destinations, motion drops, duplicates.
    """
    unique, duplicates = _dedupe(list(keepers))
    items = [
        PlanItem(
            key=str(keeper.source),
            taken_at=keeper.metadata.taken_at,
            extension=keeper.extension,
            fallback_name=keeper.source.name,
        )
        for keeper in unique
    ]
    destinations = plan_moves(items)
    placements = tuple(
        Placement(
            source=keeper.source,
            destination=destinations[str(keeper.source)],
            is_video=keeper.is_video,
            metadata=keeper.metadata,
            source_tag=keeper.source_tag,
        )
        for keeper in unique
    )
    return LibraryPlan(
        placements=placements,
        motion_drops=tuple(motion),
        duplicate_drops=tuple(duplicates),
    )


def summarize(plan: LibraryPlan) -> PlanSummary:
    """Aggregate a plan into counts for the audit report.

    Args:
        plan: The library plan.

    Returns:
        Aggregate counts (by source, by year, motion drops).
    """
    by_source = Counter(placement.source_tag.value for placement in plan.placements)
    by_year = Counter(
        placement.metadata.taken_at.year
        for placement in plan.placements
        if placement.metadata.taken_at is not None
    )
    return PlanSummary(
        keepers=len(plan.placements),
        photos=sum(1 for placement in plan.placements if not placement.is_video),
        videos=sum(1 for placement in plan.placements if placement.is_video),
        undated=sum(
            1 for placement in plan.placements if placement.destination.is_relative_to(UNSORTED)
        ),
        by_source=dict(by_source),
        by_year=dict(sorted(by_year.items())),
        motion_count=len(plan.motion_drops),
        motion_bytes=sum(drop.size for drop in plan.motion_drops),
        duplicate_count=len(plan.duplicate_drops),
        duplicate_bytes=sum(duplicate.size for duplicate in plan.duplicate_drops),
    )


def _load_json(path: Path) -> Mapping[str, object] | None:
    try:
        with path.open("rb") as handle:
            data = json.load(handle)
    except (OSError, ValueError):
        return None
    return data if isinstance(data, dict) else None


def _size(path: Path) -> int:
    try:
        return path.stat().st_size
    except OSError:
        return 0


def _photo_extension(path: Path) -> str:
    # Fall back to the (lower-cased) name only when the content is unrecognised.
    return content_extension(path) or path.suffix.lower()


def _scan_dir(root_and_files: tuple[Path, list[str]]) -> tuple[list[Keeper], list[Drop]]:
    root, files = root_and_files
    pairing = pair_directory(files)
    resolved = resolve_directory(
        pairing,
        load_sidecar=lambda name: _load_json(root / name),
        read_exif=lambda name: read_capture(root / name),
    )
    by_name = {item.name: item for item in resolved}
    keepers = []
    for entry in pairing.keepers:
        resolved_entry = by_name[entry.name]
        path = root / entry.name
        # Trust the video container's name; sniff photos, whose .HEIC is often JPEG.
        extension = path.suffix.lower() if entry.is_video else _photo_extension(path)
        keeper = Keeper(
            path,
            entry.is_video,
            _size(path),
            extension,
            resolved_entry.metadata,
            resolved_entry.source,
        )
        keepers.append(keeper)
    drops = [Drop(root / entry.name, _size(root / entry.name)) for entry in pairing.motion_videos]
    return keepers, drops


def scan(target: Path, *, jobs: int = 16) -> tuple[list[Keeper], list[Drop]]:
    """Walk ``target`` and resolve every folder's keepers and motion videos.

    Reads directory listings and sidecars only (over NFS); nothing is modified.
    Folders are processed concurrently to hide network latency.

    Args:
        target: The extracted takeout folder.
        jobs: How many folders to process at once.

    Returns:
        ``(keepers, drops)`` across the whole tree.
    """
    folders = [(Path(root), files) for root, _dirs, files in os.walk(target)]
    keepers: list[Keeper] = []
    drops: list[Drop] = []
    with ThreadPoolExecutor(max_workers=jobs) as pool:
        for folder_keepers, folder_drops in pool.map(_scan_dir, folders):
            keepers.extend(folder_keepers)
            drops.extend(folder_drops)
    return keepers, drops
