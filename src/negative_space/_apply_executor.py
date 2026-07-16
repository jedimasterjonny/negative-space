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


def _apply_one(op: dict, exiftool: list[str]) -> str:
    kind = op["kind"]
    if kind == "photo":
        argv = photo_argv(exiftool, op["taken"], op.get("lat"), op.get("lng"), op["src"])
        subprocess.run(  # noqa: S603 - argv built here, no shell
            argv, check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL
        )
        move(op["src"], op["dst"], op["mtime"])
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


def apply_manifest(manifest: list, exiftool: list[str]) -> dict[str, int]:
    """Apply every operation, tolerating per-file errors.

    Returns:
        ``"kind:outcome" -> count`` tallies, where outcome is ``ok``, ``differs``
        (a duplicate whose bytes didn't match its keeper), or ``error``.
    """
    counts: dict[str, int] = {}
    for op in manifest:
        kind = op["kind"]
        try:
            outcome = _apply_one(op, exiftool)
        except (OSError, subprocess.CalledProcessError) as exc:
            outcome = "error"
            sys.stderr.write(str(exc) + "\n")
        key = kind + ":" + outcome
        counts[key] = counts.get(key, 0) + 1
    return counts


if __name__ == "__main__":  # pragma: no cover - the NAS entry point
    manifest_path, exiftool_words = sys.argv[1], sys.argv[2:]
    result = apply_manifest(
        json.loads(Path(manifest_path).read_text(encoding="utf-8")), exiftool_words
    )
    sys.stdout.write(json.dumps(result) + "\n")
