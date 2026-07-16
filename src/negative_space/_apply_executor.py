"""Apply an organise manifest on the NAS (standalone, Python 3.8 compatible).

This module is shipped to and run *on the NAS*, where Python is 3.8 and the
files are local, so it deliberately avoids negative_space imports and 3.10+
syntax. It reads a JSON manifest of operations and applies each one:

* ``photo``     -- rewrite metadata with exiftool, move to the dated path, set mtime
* ``video``     -- move to the dated path, set mtime
* ``undated``   -- move to ``unsorted/`` as-is
* ``motion``    -- delete (a motion-photo video)
* ``duplicate`` -- delete only if byte-identical to the copy being kept
"""

from __future__ import annotations

import hashlib
import json
import os
import subprocess  # noqa: S404 - runs the exiftool command passed in on argv, no shell
import sys
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Callable


def photo_argv(
    exiftool: list[str], taken: str, lat: float | None, lng: float | None, src: str
) -> list[str]:
    """Build the exiftool argv that rewrites one photo's metadata in place.

    Returns:
        The full argv: the exiftool command, the strip/keep flags, the date and
        (if present) GPS tags, and the source path.
    """
    argv = [
        *exiftool,
        "-q",
        "-overwrite_original",
        "-all=",
        "-tagsFromFile",
        "@",
        "-ICC_Profile",
        "-Orientation",
        "-Make",
        "-Model",
        "-DateTimeOriginal=" + taken,
    ]
    if lat is not None and lng is not None:
        argv += [
            "-GPSLatitude=" + repr(abs(lat)),
            "-GPSLatitudeRef=" + ("S" if lat < 0 else "N"),
            "-GPSLongitude=" + repr(abs(lng)),
            "-GPSLongitudeRef=" + ("W" if lng < 0 else "E"),
        ]
    argv.append(src)
    return argv


def digest(path: str) -> str:
    """Return the MD5 of a file (integrity/dedup check, not security)."""
    hasher = hashlib.md5()  # noqa: S324 - comparing two local copies, not a security control
    with Path(path).open("rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            hasher.update(chunk)
    return hasher.hexdigest()


def move(src: str, dst: str, mtime: float | None) -> None:
    """Move ``src`` to ``dst`` (creating parents) and optionally set its mtime."""
    destination = Path(dst)
    destination.parent.mkdir(parents=True, exist_ok=True)
    Path(src).rename(destination)
    if mtime is not None:
        os.utime(destination, (mtime, mtime))


def rewrite(exiftool: list[str], op: dict) -> None:
    """Move a photo to its dated path, rewrite its metadata, then set its mtime.

    The move happens first so exiftool operates on the destination, whose
    extension reflects the true content (a JPEG mislabelled ``.HEIC`` becomes a
    ``.jpg`` exiftool will actually write). The mtime is set last because the
    rewrite touches it.
    """
    move(op["src"], op["dst"], None)
    argv = photo_argv(exiftool, op["taken"], op.get("lat"), op.get("lng"), op["dst"])
    subprocess.run(  # noqa: S603 - argv built here, no shell
        argv, check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL
    )
    os.utime(op["dst"], (op["mtime"], op["mtime"]))


def _apply_one(op: dict, exiftool: list[str]) -> str:
    kind = op["kind"]
    if kind == "photo":
        rewrite(exiftool, op)
    elif kind == "video":
        move(op["src"], op["dst"], op["mtime"])
    elif kind == "undated":
        move(op["src"], op["dst"], None)
    elif kind == "motion":
        Path(op["src"]).unlink()
    elif kind == "duplicate":
        if digest(op["src"]) != digest(op["kept"]):
            return "differs"  # keep it — apply never deletes a copy it can't verify
        Path(op["src"]).unlink()
    # Any other kind is left untouched: build_manifest only emits the five above,
    # so an unrecognised op is a no-op rather than a reason to touch a file.
    return "ok"


def _already_done(op: dict) -> bool:
    # Makes a re-run resumable: a move whose source is gone and destination is in
    # place is finished; a delete whose source is gone is finished.
    src_gone = not Path(op["src"]).exists()
    if op["kind"] in {"photo", "video", "undated"}:
        return src_gone and Path(op["dst"]).exists()
    return src_gone


def apply_manifest(
    manifest: list,
    exiftool: list[str],
    on_progress: Callable[[int, int], None] = lambda _done, _total: None,
    progress_every: int = 500,
) -> dict[str, int]:
    """Apply every operation, tolerating per-file errors and skipping done work.

    Args:
        manifest: The operations to apply.
        exiftool: The exiftool command as argv words (e.g. ``["perl", "/…/exiftool"]``).
        on_progress: Called with ``(done, total)`` every ``progress_every`` ops
            and once at the end.
        progress_every: How often to report progress.

    Returns:
        ``"kind:outcome" -> count`` tallies. Outcome is ``ok``, ``skip`` (already
        applied), ``differs`` (a duplicate whose bytes didn't match its keeper),
        or ``error``.
    """
    counts: dict[str, int] = {}
    total = len(manifest)
    for index, op in enumerate(manifest, start=1):
        kind = op["kind"]
        if _already_done(op):
            outcome = "skip"
        else:
            try:
                outcome = _apply_one(op, exiftool)
            except (OSError, subprocess.CalledProcessError) as exc:
                outcome = "error"
                sys.stderr.write(str(exc) + "\n")
        key = kind + ":" + outcome
        counts[key] = counts.get(key, 0) + 1
        if index % progress_every == 0 or index == total:
            on_progress(index, total)
    return counts


if __name__ == "__main__":  # pragma: no cover - the NAS entry point
    manifest_path, exiftool_words = sys.argv[1], sys.argv[2:]
    ops = json.loads(Path(manifest_path).read_text(encoding="utf-8"))

    def _emit(done: int, total: int) -> None:
        percent = done * 100 // total if total else 100
        sys.stdout.write(f"  {done}/{total} ({percent}%)\n")
        sys.stdout.flush()

    result = apply_manifest(ops, exiftool_words, _emit)
    # The orchestrator reads this back over SSH; stdout is only for live progress.
    Path(manifest_path).with_name("result.json").write_text(json.dumps(result), encoding="utf-8")
    sys.stdout.write("RESULT " + json.dumps(result) + "\n")
