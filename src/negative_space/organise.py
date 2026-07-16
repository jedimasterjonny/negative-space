"""Plan where each kept file goes in the organised library.

Dated files land in ``<year>/<month> - <month name>/`` named
``YYYY-MM-DD HH-MM-SS`` so a plain sort is chronological; two files sharing a
second get a `` (2)`` suffix. Undated files go to a top-level ``unsorted/``
folder under their original name. The planner is pure -- it turns a list of
items into a collision-free set of destination paths and does not touch disk.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import PurePosixPath
from typing import TYPE_CHECKING, Final

if TYPE_CHECKING:
    import datetime
    from collections.abc import Iterable

_MONTHS: Final = (
    "January",
    "February",
    "March",
    "April",
    "May",
    "June",
    "July",
    "August",
    "September",
    "October",
    "November",
    "December",
)
#: Top-level folder for files with no resolved date (or that can't be rewritten).
UNSORTED: Final = PurePosixPath("unsorted")
#: Image formats exiftool cannot write metadata to, so they can't be dated in
#: place -- they go to ``unsorted/`` as-is rather than a dated folder.
NON_REWRITABLE: Final = frozenset({".bmp"})
_STEM_FORMAT: Final = "%Y-%m-%d %H-%M-%S"


@dataclass(frozen=True, slots=True)
class PlanItem:
    """One file to place: its date (or ``None``) and how to name it."""

    key: str  # unique source identifier, e.g. the file's path in the takeout
    taken_at: datetime.datetime | None
    extension: str  # e.g. ".jpg"
    fallback_name: str  # original file name, used when undated


def capture_folder(taken_at: datetime.datetime) -> PurePosixPath:
    """Return the ``<year>/<month number> - <month name>`` folder for a date."""
    month = f"{taken_at.month:02d} - {_MONTHS[taken_at.month - 1]}"
    return PurePosixPath(f"{taken_at.year:04d}", month)


def _dated(item: PlanItem) -> bool:
    # Placed in a dated folder only with a date *and* a rewritable format;
    # otherwise it can't be dated in place, so it goes to unsorted as-is.
    return item.taken_at is not None and item.extension.lower() not in NON_REWRITABLE


def _base(item: PlanItem) -> tuple[PurePosixPath, str, str]:
    taken = item.taken_at
    if taken is not None and item.extension.lower() not in NON_REWRITABLE:
        return capture_folder(taken), taken.strftime(_STEM_FORMAT), item.extension.lower()
    original = PurePosixPath(item.fallback_name)
    return UNSORTED, original.stem, original.suffix


def _unique(item: PlanItem, taken: set[str]) -> PurePosixPath:
    folder, stem, extension = _base(item)
    counter = 0
    while True:
        name = stem if counter == 0 else f"{stem} ({counter + 1})"
        candidate = folder / f"{name}{extension}"
        if str(candidate) not in taken:
            return candidate
        counter += 1


def plan_moves(items: Iterable[PlanItem]) -> dict[str, PurePosixPath]:
    """Assign every item a unique destination path in the organised library.

    Dated items are placed first (chronologically), then undated ones by name,
    so destinations are deterministic regardless of input order.

    Args:
        items: The files to place.

    Returns:
        A mapping of each item's ``key`` to its destination path, relative to
        the library root.
    """
    items = list(items)
    dated = [item for item in items if _dated(item)]
    undated = [item for item in items if not _dated(item)]
    dated.sort(key=lambda item: (item.taken_at, item.key))
    undated.sort(key=lambda item: (item.fallback_name, item.key))

    taken: set[str] = set()
    moves: dict[str, PurePosixPath] = {}
    for item in (*dated, *undated):
        destination = _unique(item, taken)
        taken.add(str(destination))
        moves[item.key] = destination
    return moves
