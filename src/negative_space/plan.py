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

from negative_space.exif import read_capture
from negative_space.metadata import resolve_directory
from negative_space.organise import PlanItem, plan_moves
from negative_space.pairing import pair_directory

if TYPE_CHECKING:
    from collections.abc import Iterable, Mapping
    from pathlib import PurePosixPath

    from negative_space.metadata import MetadataSource, PhotoMetadata


@dataclass(frozen=True, slots=True)
class Keeper:
    """A media file to keep, with its resolved metadata."""

    source: Path
    is_video: bool
    metadata: PhotoMetadata
    source_tag: MetadataSource


@dataclass(frozen=True, slots=True)
class Drop:
    """A motion-photo video to delete, with its size."""

    source: Path
    size: int


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
    drops: tuple[Drop, ...]


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


def build_plan(keepers: Iterable[Keeper], drops: Iterable[Drop]) -> LibraryPlan:
    """Assign every keeper a destination and collect the motion-video drops.

    Args:
        keepers: Media files to keep, with resolved metadata.
        drops: Motion-photo videos to delete.

    Returns:
        The library plan with collision-free destinations.
    """
    keepers = list(keepers)
    items = [
        PlanItem(
            key=str(keeper.source),
            taken_at=keeper.metadata.taken_at,
            extension=keeper.source.suffix,
            fallback_name=keeper.source.name,
        )
        for keeper in keepers
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
        for keeper in keepers
    )
    return LibraryPlan(placements=placements, drops=tuple(drops))


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
        undated=sum(1 for placement in plan.placements if placement.metadata.taken_at is None),
        by_source=dict(by_source),
        by_year=dict(sorted(by_year.items())),
        motion_count=len(plan.drops),
        motion_bytes=sum(drop.size for drop in plan.drops),
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
        keeper = Keeper(
            root / entry.name, entry.is_video, resolved_entry.metadata, resolved_entry.source
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
