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

# Google appends ".supplemental-metadata.json" to the media name, then truncates
# the whole result to a hard character limit -- cutting the suffix (and even the
# media extension) from the right while always keeping a trailing ".json". So a
# sidecar name is derived *forwards* from its media file, not parsed back.
_SIDECAR_SUFFIX: Final = ".supplemental-metadata"
_SIDECAR_LIMIT: Final = 51
# Suffix Google appends to an edited copy (English exports), before the extension
# and truncated to the same limit, e.g. "...ORIGINAL-edited.jpg" -> "...-edi.jpg".
# An edited copy has no sidecar of its own and inherits the original's metadata.
_EDITED_SUFFIX: Final = "-edited"
# Trailing "(N)" duplicate marker before an extension, e.g. "photo(1).jpg".
_NUMBERED: Final = re.compile(r"^(.*)\((\d+)\)(\.[^.]+)$")
# JSON files that are not per-photo sidecars.
_SPECIAL_JSON: Final = frozenset(
    {
        "metadata.json",
        "shared_album_comments.json",
        "user-generated-memory-titles.json",
        "print-subscriptions.json",
    },
)


def extension(name: str) -> str:
    """Return the lower-cased extension of ``name`` (including the leading dot)."""
    return PurePosixPath(name).suffix.lower()


def is_image(name: str) -> bool:
    """Return whether ``name`` has a still-image extension."""
    return extension(name) in IMAGE_EXTS


def is_video(name: str) -> bool:
    """Return whether ``name`` has a video extension."""
    return extension(name) in VIDEO_EXTS


def _truncate_sidecar(stem: str) -> str:
    full = f"{stem}.json"
    if len(full) <= _SIDECAR_LIMIT:
        return full
    return stem[: _SIDECAR_LIMIT - len(".json")] + ".json"


def expected_sidecars(name: str) -> list[str]:
    """Return the sidecar file names a media file's metadata could live in.

    The sidecar is ``<media>.supplemental-metadata.json`` truncated to Takeout's
    length limit. A numbered duplicate ``photo(1).jpg`` has its metadata under the
    base name's JSON with the marker appended *after* truncation (so the ``(N)``
    is preserved even when it pushes the name past the limit):
    ``photo.jpg.supplemental-metadata(1).json``.

    Args:
        name: A media file name.

    Returns:
        Candidate sidecar file names, most specific first.
    """
    candidates = [_truncate_sidecar(name + _SIDECAR_SUFFIX)]
    dup = _NUMBERED.match(name)
    if dup is not None:
        base = f"{dup.group(1)}{dup.group(3)}"
        base_sidecar = _truncate_sidecar(base + _SIDECAR_SUFFIX)
        candidates.append(f"{base_sidecar[:-5]}({dup.group(2)}).json")
    return candidates


def _stem(name: str) -> str:
    ext = extension(name)
    return name[: -len(ext)] if ext else name


def edited_original(name: str, media_set: set[str]) -> str | None:
    """Return the original a ``-edited`` copy derives from, if present.

    Args:
        name: A media file name.
        media_set: All media file names in the same folder.

    Returns:
        The original's file name (``name`` with the ``-edited`` suffix removed,
        allowing for length-truncated forms like ``-edi``), or ``None``.
    """
    stem, _, ext = name.rpartition(".")
    if not stem:
        return None
    ext = f".{ext}"
    for length in range(len(_EDITED_SUFFIX), 1, -1):
        if not stem.endswith(_EDITED_SUFFIX[:length]):
            continue
        # A partial "-edited" only occurs when the full suffix would overflow.
        full_length = len(stem) - length + len(_EDITED_SUFFIX) + len(ext)
        if length < len(_EDITED_SUFFIX) and full_length <= _SIDECAR_LIMIT:
            continue
        original = stem[:-length] + ext
        if original in media_set:
            return original
    return None


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


@dataclass(frozen=True, slots=True)
class MediaEntry:
    """A media file with its resolved sidecar, motion-photo and edit status."""

    name: str
    is_video: bool
    sidecar: str | None
    motion_still: str | None
    original: str | None = None

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
    name_set = set(names)
    images = [name for name in names if is_image(name)]
    videos = [name for name in names if is_video(name)]
    image_stems = {_stem(image).lower(): image for image in images}
    media_set = {*images, *videos}

    claimed: set[str] = set()
    entries: list[MediaEntry] = []
    for name in (*images, *videos):
        video = is_video(name)
        sidecar = next(
            (cand for cand in expected_sidecars(name) if cand in name_set and cand not in claimed),
            None,
        )
        if sidecar is not None:
            claimed.add(sidecar)
        entries.append(
            MediaEntry(
                name=name,
                is_video=video,
                sidecar=sidecar,
                motion_still=motion_still(name, image_stems) if video else None,
                original=None if sidecar else edited_original(name, media_set),
            ),
        )

    orphans: list[str] = []
    other: list[str] = []
    for name in names:
        if name in media_set or name in claimed:
            continue
        if name.endswith(".json") and name not in _SPECIAL_JSON:
            orphans.append(name)
        else:
            other.append(name)
    return DirectoryPairing(
        entries=tuple(entries),
        orphan_sidecars=tuple(sorted(orphans)),
        other=tuple(sorted(other)),
    )
