"""Apply an organise manifest on the NAS (standalone, Python 3.8 compatible).

This module is shipped to and run *on the NAS*, where Python is 3.8 and the
files are local, so it deliberately avoids negative_space imports and 3.10+
syntax. It reads a JSON manifest of operations and applies each one:

* ``photo``     -- rewrite metadata with exiftool, move to the dated path, set mtime
* ``video``     -- move to the dated path, set mtime
* ``undated``   -- move to ``unsorted/`` as-is
* ``motion``    -- delete (a motion-photo video)
* ``duplicate`` -- delete only if byte-identical to the copy being kept

Photos are rewritten in *batches*: spawning ``perl exiftool`` once per photo is
~18x slower than feeding many files to a single process via an argument file.
To keep a re-run resumable, a photo is only moved out of the input tree once it
has been rewritten -- so exiftool must rewrite it *in place*, under its true
extension. Google Takeout mislabels many JPEGs as ``.HEIC``; exiftool writes by
extension, so each photo is rewritten through a hardlink named with its true
extension while ``-overwrite_original_in_place`` preserves the shared inode.
"""

from __future__ import annotations

import contextlib
import hashlib
import json
import os
import subprocess  # noqa: S404 - runs the exiftool command passed in on argv, no shell
import sys
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Callable

_CHUNK = 256  # photos rewritten per exiftool process


def photo_flags(op: dict) -> list[str]:
    """Build the exiftool flags that strip and re-stamp one photo's metadata.

    Returns:
        The flags (no exiftool command, no file): strip-all, restore the kept
        tags, set the date and, when present, GPS. In-place so a hardlink can
        stand in for the true-extension while the real file is rewritten.
    """
    flags = [
        "-overwrite_original_in_place",
        "-all=",
        "-tagsFromFile",
        "@",
        "-ICC_Profile",
        "-Orientation",
        "-Make",
        "-Model",
        "-DateTimeOriginal=" + op["taken"],
    ]
    lat, lng = op.get("lat"), op.get("lng")
    if lat is not None and lng is not None:
        flags += [
            "-GPSLatitude=" + repr(abs(lat)),
            "-GPSLatitudeRef=" + ("S" if lat < 0 else "N"),
            "-GPSLongitude=" + repr(abs(lng)),
            "-GPSLongitudeRef=" + ("W" if lng < 0 else "E"),
        ]
    return flags


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


def _unlink_quietly(path: str) -> None:
    with contextlib.suppress(OSError):
        Path(path).unlink()


def _hardlink(op: dict, links_dir: str, index: int) -> str:
    # A hardlink named with the destination's (true) extension; rewriting it in
    # place edits the shared inode, i.e. the real source, which stays put.
    extension = Path(op["dst"]).suffix or ".jpg"
    link = str(Path(links_dir) / f"l{index}{extension}")
    os.link(op["src"], link)  # Path.hardlink_to is 3.10+; the NAS runs 3.8
    return link


def _rewrite_batch(exiftool: list[str], chunk: list, links_dir: str) -> bool:
    # Rewrite the whole chunk in one exiftool process; True iff all succeeded.
    links = []
    lines: list[str] = []
    try:
        for index, op in enumerate(chunk):
            link = _hardlink(op, links_dir, index)
            links.append(link)
            lines.extend(photo_flags(op))
            lines.extend((link, "-execute"))
        argfile = str(Path(links_dir) / "args")
        Path(argfile).write_text("\n".join(lines) + "\n", encoding="utf-8")
        completed = subprocess.run(  # noqa: S603 - argv built here, no shell
            [*exiftool, "-q", "-@", argfile],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            check=False,
        )
        return completed.returncode == 0
    finally:
        for link in links:
            _unlink_quietly(link)


def _rewrite_one(exiftool: list[str], op: dict, links_dir: str) -> None:
    # Rewrite a single photo; raises on failure so the caller can tally it.
    link = _hardlink(op, links_dir, 0)
    try:
        subprocess.run(  # noqa: S603 - argv built here, no shell
            [*exiftool, "-q", *photo_flags(op), link],
            check=True,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
    finally:
        _unlink_quietly(link)


def _flush_photos(exiftool: list[str], chunk: list, links_dir: str, counts: dict[str, int]) -> None:
    if _rewrite_batch(exiftool, chunk, links_dir):
        for op in chunk:
            move(op["src"], op["dst"], op["mtime"])
            _tally(counts, "photo:ok")
        return
    # The batch reported a failure; re-run each file to find and skip the culprit.
    for op in chunk:
        try:
            _rewrite_one(exiftool, op, links_dir)
            move(op["src"], op["dst"], op["mtime"])
        except (OSError, subprocess.CalledProcessError) as exc:
            _tally(counts, "photo:error")
            sys.stderr.write("ERROR photo {}: {}\n".format(op["src"], exc))
        else:
            _tally(counts, "photo:ok")


def _apply_drop_or_move(op: dict) -> str:
    kind = op["kind"]
    if kind == "video":
        move(op["src"], op["dst"], op["mtime"])
    elif kind == "undated":
        move(op["src"], op["dst"], None)
    elif kind == "motion":
        Path(op["src"]).unlink()
    elif kind == "duplicate":
        if digest(op["src"]) != digest(op["kept"]):
            return "differs"  # keep it — apply never deletes a copy it can't verify
        Path(op["src"]).unlink()
    return "ok"


def _already_done(op: dict) -> bool:
    # Makes a re-run resumable: a move whose source is gone and destination is in
    # place is finished; a delete whose source is gone is finished.
    src_gone = not Path(op["src"]).exists()
    if op["kind"] in {"photo", "video", "undated"}:
        return src_gone and Path(op["dst"]).exists()
    return src_gone


def _tally(counts: dict[str, int], key: str) -> None:
    counts[key] = counts.get(key, 0) + 1


def _prepare_links_dir(links_dir: str) -> None:
    path = Path(links_dir)
    path.mkdir(parents=True, exist_ok=True)
    for entry in path.iterdir():  # clear stale links from an interrupted run
        _unlink_quietly(str(entry))


def apply_manifest(
    manifest: list,
    exiftool: list[str],
    links_dir: str,
    on_progress: Callable[[int, int], None] = lambda _done, _total: None,
    progress_every: int = 500,
) -> dict[str, int]:
    """Apply every operation, batching photo rewrites and skipping done work.

    Args:
        manifest: The operations to apply.
        exiftool: The exiftool command as argv words (e.g. ``["perl", "/…/exiftool"]``).
        links_dir: A scratch dir on the source's filesystem for the rewrite hardlinks.
        on_progress: Called with ``(done, total)`` periodically and once at the end.
        progress_every: Roughly how many ops between progress reports.

    Returns:
        ``"kind:outcome" -> count`` tallies. Outcome is ``ok``, ``skip`` (already
        applied), ``differs`` (a duplicate whose bytes didn't match its keeper),
        or ``error``.
    """
    _prepare_links_dir(links_dir)
    counts: dict[str, int] = {}
    total = len(manifest)
    processed = last_reported = 0
    pending: list = []
    for op in manifest:
        kind = op["kind"]
        if _already_done(op):
            _tally(counts, kind + ":skip")
            processed += 1
        elif kind == "photo":
            pending.append(op)
            if len(pending) >= _CHUNK:
                _flush_photos(exiftool, pending, links_dir, counts)
                processed += len(pending)
                pending = []
        else:
            try:
                outcome = _apply_drop_or_move(op)
            except OSError as exc:
                outcome = "error"
                sys.stderr.write("ERROR {} {}: {}\n".format(kind, op.get("src", "?"), exc))
            _tally(counts, kind + ":" + outcome)
            processed += 1
        if processed - last_reported >= progress_every:
            on_progress(processed, total)
            last_reported = processed
    if pending:
        _flush_photos(exiftool, pending, links_dir, counts)
        processed += len(pending)
    on_progress(processed, total)
    return counts


if __name__ == "__main__":  # pragma: no cover - the NAS entry point
    manifest_path, exiftool_words = sys.argv[1], sys.argv[2:]
    ops = json.loads(Path(manifest_path).read_text(encoding="utf-8"))
    scratch = str(Path(manifest_path).with_name("links"))

    def _emit(done: int, total: int) -> None:
        sys.stdout.write(f"PROGRESS {done} {total}\n")
        sys.stdout.flush()

    result = apply_manifest(ops, exiftool_words, scratch, _emit)
    Path(manifest_path).with_name("result.json").write_text(json.dumps(result), encoding="utf-8")
    sys.stdout.write("RESULT " + json.dumps(result) + "\n")
