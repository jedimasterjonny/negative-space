"""Discover the Google Photos takeout archives to extract.

A takeout is delivered as a set of ``takeout-*.tgz`` files. Each one is an
independent gzip+tar, so they can be extracted in any order and in parallel.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from typing import Final

#: Suffixes Google Takeout uses for tar+gzip archives.
_ARCHIVE_SUFFIXES: Final = (".tgz", ".tar.gz")


@dataclass(frozen=True, slots=True)
class Archive:
    """A single takeout archive on the local (NFS) filesystem."""

    path: Path
    size: int

    @property
    def name(self) -> str:
        """The archive's file name."""
        return self.path.name


def discover(target: Path) -> list[Archive]:
    """Find takeout archives directly inside ``target``.

    Uses a single directory scan and reads each entry's size, so it makes one
    round trip for the listing plus one stat per archive — not a recursive walk.

    Args:
        target: Folder holding the ``*.tgz`` archives.

    Returns:
        Archives sorted by file name (which orders the takeout's numbered parts).
    """
    with os.scandir(target) as entries:
        archives = [
            Archive(path=Path(entry.path), size=entry.stat().st_size)
            for entry in entries
            if entry.name.endswith(_ARCHIVE_SUFFIXES) and entry.is_file(follow_symlinks=False)
        ]
    return sorted(archives, key=lambda archive: archive.name)
