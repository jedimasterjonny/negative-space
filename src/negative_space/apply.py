"""Lower a plan to an apply manifest and drive the destructive apply on the NAS.

:func:`build_manifest` turns a read-only :class:`~negative_space.plan.LibraryPlan`
into JSON-serialisable operation dicts whose paths are the NAS's *own* local
paths. :func:`run_apply` ships those (plus the standalone executor) to the NAS
and runs them over SSH, so the executor does all its file I/O locally and
nothing but the manifest and progress crosses the network.
"""

from __future__ import annotations

import datetime
import json
import shlex
import subprocess  # noqa: S404 - only runs ssh with commands built from quoted paths
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING

from negative_space.nas import NasError, resolve_remote, ssh_argv
from negative_space.organise import UNSORTED

if TYPE_CHECKING:
    from collections.abc import Callable

    from negative_space.nas import NfsMount
    from negative_space.plan import LibraryPlan

# The executor ships as a sibling file; it must stay import-free and 3.8-safe.
_EXECUTOR = Path(__file__).with_name("_apply_executor.py")


def _no_progress(_done: int, _total: int) -> None:
    """Default progress sink: ignore updates."""


@dataclass(frozen=True, slots=True)
class ApplyTarget:
    """Where and how to apply on the NAS."""

    mount: NfsMount
    exiftool: str  # e.g. "perl /…/exiftool"
    output_root: str  # NAS path the organised library is written under
    work_dir: str  # NAS scratch dir for the executor, manifest and result


@dataclass(frozen=True, slots=True)
class ApplyOutcome:
    """The result of a destructive apply run."""

    plan: LibraryPlan
    counts: dict[str, int]  # "kind:outcome" -> count, straight from the executor


def _epoch(when: datetime.datetime) -> int:
    # Metadata datetimes are naive UTC throughout; stamp mtime as a UTC epoch.
    return int(when.replace(tzinfo=datetime.UTC).timestamp())


def build_manifest(
    plan: LibraryPlan, *, output_root: str, to_nas: Callable[[Path], str]
) -> list[dict[str, object]]:
    """Lower a plan to NAS-local operations for the executor.

    Each placement becomes a ``photo`` (exiftool rewrite + move + mtime),
    ``video`` (move + mtime) or ``undated`` (move as-is, for anything in
    ``unsorted/`` -- undated files or BMPs exiftool can't rewrite) op; each drop
    becomes a ``motion`` (delete) or ``duplicate`` (hash-verify then delete) op.

    Drops are emitted *before* placements: a duplicate is hash-verified against
    the copy being kept, and that copy is itself a placement whose move (and
    rewrite) would relocate and alter its bytes. Verifying first, while both
    originals are still in place, is what makes the check meaningful.

    Args:
        plan: The read-only library plan.
        output_root: The NAS path the organised library is written under.
        to_nas: Maps a source path on the NFS mount to its NAS-local path.

    Returns:
        The operations: duplicate and motion drops first, then placements.
    """
    ops: list[dict[str, object]] = [
        {"kind": "duplicate", "src": to_nas(dup.source), "kept": to_nas(dup.kept)}
        for dup in plan.duplicate_drops
    ]
    ops += [{"kind": "motion", "src": to_nas(drop.source)} for drop in plan.motion_drops]
    for placement in plan.placements:
        src = to_nas(placement.source)
        dst = output_root + "/" + placement.destination.as_posix()
        taken = placement.metadata.taken_at
        # Anything routed to unsorted/ (undated, or a format exiftool can't
        # rewrite like BMP) is moved as-is; only dated, rewritable media is dated.
        if taken is None or placement.destination.is_relative_to(UNSORTED):
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
    return ops


def _remote_command(work_dir: str, exiftool: str) -> str:
    """Build the shell command that runs the executor inside ``work_dir``.

    Returns:
        A ``cd … && python3 …`` command for the NAS's shell.
    """
    return f"cd {shlex.quote(work_dir)} && python3 _apply_executor.py manifest.json {exiftool}"


def _put(
    host: str, dest: str, content: str, runner: Callable[..., subprocess.CompletedProcess[str]]
) -> None:
    runner(
        ssh_argv(host, "cat > " + shlex.quote(dest)),
        input=content,
        check=True,
        capture_output=True,
        text=True,
    )


def ship(
    host: str,
    work_dir: str,
    manifest: list[dict[str, object]],
    *,
    runner: Callable[..., subprocess.CompletedProcess[str]] = subprocess.run,
) -> None:
    """Create ``work_dir`` on the NAS and upload the executor and manifest."""
    runner(
        ssh_argv(host, "mkdir -p " + shlex.quote(work_dir)),
        check=True,
        capture_output=True,
        text=True,
    )
    _put(host, work_dir + "/_apply_executor.py", _EXECUTOR.read_text(encoding="utf-8"), runner)
    _put(host, work_dir + "/manifest.json", json.dumps(manifest), runner)


def run_executor(
    host: str,
    work_dir: str,
    exiftool: str,
    *,
    log_path: Path,
    on_progress: Callable[[int, int], None],
) -> dict[str, int]:
    """Run the executor on the NAS, teeing its output to ``log_path`` as it goes.

    Every line the executor emits is written to ``log_path`` (so a failed run
    leaves a full record), progress lines drive ``on_progress``, and the final
    ``RESULT`` line carries the tallies. The executor's stderr is folded in so
    per-file errors and any crash land in the same log.

    Returns:
        The ``"kind:outcome" -> count`` tallies.

    Raises:
        NasError: If the executor exits non-zero (the message points at the log).
    """
    argv = ssh_argv(host, _remote_command(work_dir, exiftool))
    counts: dict[str, int] = {}
    with log_path.open("w", encoding="utf-8") as log:
        process = subprocess.Popen(  # noqa: S603 - argv is ssh with a quoted command
            argv, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, bufsize=1
        )
        with process:
            stream = process.stdout
            if stream is None:  # pragma: no cover - stdout is always a pipe here
                stream = []
            for line in stream:
                log.write(line)
                log.flush()  # keep the log usable live and intact if the run dies
                text = line.strip()
                if text.startswith("PROGRESS "):
                    _, done, total = text.split()
                    on_progress(int(done), int(total))
                elif text.startswith("RESULT "):
                    counts = json.loads(text[len("RESULT ") :])
    if process.returncode:
        msg = f"apply executor failed on {host} (exit {process.returncode}); see {log_path}"
        raise NasError(msg)
    return counts


def run_apply(
    plan: LibraryPlan,
    target: ApplyTarget,
    *,
    log_path: Path,
    on_progress: Callable[[int, int], None] = _no_progress,
) -> ApplyOutcome:
    """Apply ``plan`` on the NAS: build the manifest, ship it, run it, read results.

    Args:
        plan: The reorganisation to carry out.
        target: Where and how to apply on the NAS.
        log_path: Local file to tee the executor's progress and errors into.
        on_progress: Called with ``(done, total)`` as the run advances.

    Returns:
        The plan and the executor's per-outcome counts.
    """

    def to_nas(path: Path) -> str:
        return str(resolve_remote(path, target.mount).path)

    manifest = build_manifest(plan, output_root=target.output_root, to_nas=to_nas)
    ship(target.mount.host, target.work_dir, manifest)
    counts = run_executor(
        target.mount.host,
        target.work_dir,
        target.exiftool,
        log_path=log_path,
        on_progress=on_progress,
    )
    return ApplyOutcome(plan=plan, counts=counts)
