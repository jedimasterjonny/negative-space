"""Pair takeout media with their sidecars and flag motion-photo videos.

Google Takeout scatters three complications through every album folder, which
this module untangles from a directory's raw file list:

* **Truncated sidecars** — a photo's metadata file is
  ``photo.jpg.supplemental-metadata.json`` but the ``supplemental-metadata``
  part is cut to fit a length limit, so it can be any prefix down to
  ``photo.jpg.supplement.json``, optionally with a ``(N)`` duplicate marker.
  The *media* name is always preserved, so stripping that tail recovers it.
* **Motion photos** ship the still and a short video separately, in two layouts:
  a shared base name (``MVIMG_x.MP4`` beside ``MVIMG_x.jpg``) or the still named
  after the whole video (``PXL_x.MP`` beside ``PXL_x.MP.jpg``). The video half is
  redundant with the still and can be dropped.

The result lets the organiser keep stills and real videos (with their metadata)
and drop the motion-photo video halves.
"""

from __future__ import annotations

import re
from collections import defaultdict
from dataclasses import dataclass
from pathlib import PurePosixPath
from typing import TYPE_CHECKING, Final

if TYPE_CHECKING:
    from collections.abc import Iterable

#: Still-image extensions (lower-case, with leading dot).
IMAGE_EXTS: Final = frozenset(
    {".jpg", ".jpeg", ".heic", ".heif", ".png", ".gif", ".bmp", ".webp", ".tif", ".tiff"},
)
#: Video extensions, including Pixel motion-photo ``.mp``.
VIDEO_EXTS: Final = frozenset(
    {".mp4", ".mov", ".m4v", ".mp", ".3gp", ".avi", ".mkv", ".mts", ".mpg", ".mpeg"},
)

# ".supplement" + a (possibly truncated) tail of "al-metadata", an optional
# "(N)" duplicate marker, then ".json". Matches every observed variant.
_SIDECAR_TAIL: Final = re.compile(r"\.supplement[a-z-]*(?:\(\d+\))?\.json$", re.IGNORECASE)


def extension(name: str) -> str:
    """Return the lower-cased extension of ``name`` (including the leading dot)."""
    return PurePosixPath(name).suffix.lower()


def is_image(name: str) -> bool:
    """Return whether ``name`` has a still-image extension."""
    return extension(name) in IMAGE_EXTS


def is_video(name: str) -> bool:
    """Return whether ``name`` has a video extension."""
    return extension(name) in VIDEO_EXTS


_DUP_MARKER: Final = re.compile(r"\((\d+)\)\.json$")


def sidecar_candidates(name: str) -> list[str]:
    """Return the media file names a Takeout sidecar could describe, best first.

    A ``(N)`` duplicate marker sits on the JSON but belongs to a ``(N)`` media
    file: ``photo.jpg.supplemental-metadata(1).json`` is the metadata for
    ``photo(1).jpg``, falling back to ``photo.jpg`` when no such duplicate exists
    (Takeout also emits genuine duplicate sidecars on the base name).

    Args:
        name: A file name.

    Returns:
        Candidate media names, most specific first, or an empty list if ``name``
        is not a per-photo sidecar (album ``metadata.json``, media, other files).
    """
    match = _SIDECAR_TAIL.search(name)
    if match is None or match.start() == 0:
        return []
    base = name[: match.start()]
    candidates: list[str] = []
    dup = _DUP_MARKER.search(name)
    if dup is not None:
        base_path = PurePosixPath(base)
        candidates.append(f"{base_path.stem}({dup.group(1)}){base_path.suffix}")
    candidates.append(base)
    return candidates


def _stem(name: str) -> str:
    ext = extension(name)
    return name[: -len(ext)] if ext else name


def motion_still(video: str, image_stems: dict[str, str]) -> str | None:
    """Return the still a motion-photo video belongs to, if any.

    Args:
        video: A video file name.
        image_stems: Map of lower-cased image stem to image file name.

    Returns:
        The still's file name if ``video`` is a motion-photo half (same base
        name, or the still named after the whole video), else ``None``.
    """
    return image_stems.get(_stem(video).lower()) or image_stems.get(video.lower())


def _pick_sidecar(candidates: list[str]) -> str | None:
    if not candidates:
        return None
    # Prefer a non-"(N)" name, then the least-truncated (longest) one.
    return min(candidates, key=lambda name: ("(" in name, -len(name)))


@dataclass(frozen=True, slots=True)
class MediaEntry:
    """A media file with its resolved sidecar and motion-photo status."""

    name: str
    is_video: bool
    sidecar: str | None
    motion_still: str | None

    @property
    def is_motion_video(self) -> bool:
        """Whether this is the video half of a motion photo (droppable)."""
        return self.motion_still is not None


@dataclass(frozen=True, slots=True)
class DirectoryPairing:
    """The pairing result for one album/year folder."""

    entries: tuple[MediaEntry, ...]
    orphan_sidecars: tuple[str, ...]
    other: tuple[str, ...]

    @property
    def motion_videos(self) -> tuple[MediaEntry, ...]:
        """Motion-photo video halves (safe to drop)."""
        return tuple(entry for entry in self.entries if entry.is_motion_video)

    @property
    def keepers(self) -> tuple[MediaEntry, ...]:
        """Media to keep: stills and standalone videos."""
        return tuple(entry for entry in self.entries if not entry.is_motion_video)


def pair_directory(names: Iterable[str]) -> DirectoryPairing:
    """Pair one directory's files into media, sidecars and motion videos.

    Args:
        names: File names in a single album/year folder.

    Returns:
        The structured pairing for that folder.
    """
    names = list(names)
    images = [name for name in names if is_image(name)]
    videos = [name for name in names if is_video(name)]
    media_set = {*images, *videos}

    sidecars_by_target: dict[str, list[str]] = defaultdict(list)
    other: list[str] = []
    orphans: list[str] = []
    for name in names:
        if name in media_set:
            continue
        candidates = sidecar_candidates(name)
        if not candidates:
            other.append(name)
            continue
        target = next((c for c in candidates if c in media_set), None)
        if target is None:
            orphans.append(name)
        else:
            sidecars_by_target[target].append(name)

    image_stems = {_stem(image).lower(): image for image in images}

    entries = tuple(
        MediaEntry(
            name=name,
            is_video=is_video(name),
            sidecar=_pick_sidecar(sidecars_by_target.get(name, [])),
            motion_still=motion_still(name, image_stems) if is_video(name) else None,
        )
        for name in (*images, *videos)
    )
    return DirectoryPairing(
        entries=entries,
        orphan_sidecars=tuple(sorted(orphans)),
        other=tuple(sorted(other)),
    )
