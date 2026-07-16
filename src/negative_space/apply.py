"""Lower a read-only :class:`~negative_space.plan.LibraryPlan` to an apply manifest.

The manifest is a list of plain, JSON-serialisable operation dicts that the
standalone NAS executor (:mod:`negative_space._apply_executor`) consumes. Its
paths are the NAS's *own* local paths, never the NFS mount, so the executor
does all its file I/O locally and nothing but the manifest crosses the network.
"""

from __future__ import annotations

import datetime
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Callable
    from pathlib import Path

    from negative_space.plan import LibraryPlan


def _epoch(when: datetime.datetime) -> int:
    # Metadata datetimes are naive UTC throughout; stamp mtime as a UTC epoch.
    return int(when.replace(tzinfo=datetime.UTC).timestamp())


def build_manifest(
    plan: LibraryPlan, *, output_root: str, to_nas: Callable[[Path], str]
) -> list[dict[str, object]]:
    """Lower a plan to NAS-local operations for the executor.

    Each placement becomes a ``photo`` (exiftool rewrite + move + mtime),
    ``video`` (move + mtime) or ``undated`` (move as-is) op; each drop becomes a
    ``motion`` (delete) or ``duplicate`` (hash-verify then delete) op.

    Args:
        plan: The read-only library plan.
        output_root: The NAS path the organised library is written under.
        to_nas: Maps a source path on the NFS mount to its NAS-local path.

    Returns:
        One operation dict per placement and per drop, in that order.
    """
    ops: list[dict[str, object]] = []
    for placement in plan.placements:
        src = to_nas(placement.source)
        dst = output_root + "/" + placement.destination.as_posix()
        taken = placement.metadata.taken_at
        if taken is None:
            ops.append({"kind": "undated", "src": src, "dst": dst})
        elif placement.is_video:
            ops.append({"kind": "video", "src": src, "dst": dst, "mtime": _epoch(taken)})
        else:
            op: dict[str, object] = {
                "kind": "photo",
                "src": src,
                "dst": dst,
                "mtime": _epoch(taken),
                "taken": taken.strftime("%Y:%m:%d %H:%M:%S"),
            }
            metadata = placement.metadata
            if metadata.latitude is not None and metadata.longitude is not None:
                op["lat"] = metadata.latitude
                op["lng"] = metadata.longitude
            ops.append(op)
    ops += [{"kind": "motion", "src": to_nas(drop.source)} for drop in plan.motion_drops]
    ops += [
        {"kind": "duplicate", "src": to_nas(dup.source), "kept": to_nas(dup.kept)}
        for dup in plan.duplicate_drops
    ]
    return ops
