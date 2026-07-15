"""Extract takeout archives on the NAS, with live progress.

Each archive is decompressed *on the NAS* over SSH::

    mkdir -p TARGET && dd if=ARCHIVE bs=8M status=progress | tar -xz -C TARGET

``dd`` reads the archive locally on the NAS and its ``status=progress`` output
gives a byte-accurate feed for the progress bars. Because ``tar`` is last in the
pipe, the SSH command's exit status is ``tar``'s status, and a clean exit means
gzip verified its CRC over the whole stream — so success *is* the integrity
check. Nothing but progress text crosses the network.

Archives are independent, so several extract concurrently (``jobs``). Completed
archives are recorded so an interrupted run resumes instead of starting over.
"""

from __future__ import annotations

import json
import re
import shlex
import subprocess  # noqa: S404 - only runs ssh with args built from mount config, never a shell
import threading
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, field
from typing import IO, TYPE_CHECKING, Protocol, Self

from rich.progress import (
    BarColumn,
    DownloadColumn,
    Progress,
    TaskID,
    TaskProgressColumn,
    TextColumn,
    TimeRemainingColumn,
    TransferSpeedColumn,
)

from negative_space.archives import Archive, discover
from negative_space.console import console, logger
from negative_space.nas import (
    check_ssh,
    find_mount_for,
    read_mounts,
    resolve_remote,
    ssh_argv,
)

if TYPE_CHECKING:
    from pathlib import Path, PurePosixPath
    from types import TracebackType

    from negative_space.nas import RemoteLocation

#: Resume ledger, written into the target folder (on the NAS).
STATE_FILENAME = ".negative-space-extract.json"

_CHUNK = 65536
_BYTES_RE = re.compile(rb"(\d+)\s+bytes")

#: Called with the running byte count for one archive.
OnBytes = Callable[[int], None]
#: Extracts one archive, reporting progress, and returns the process exit code.
Extractor = Callable[[Archive, OnBytes], int]


class _Process(Protocol):
    """The slice of :class:`subprocess.Popen` this module relies on."""

    stderr: IO[bytes] | None

    def wait(self) -> int: ...
    def __enter__(self) -> Self: ...
    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        traceback: TracebackType | None,
        /,
    ) -> None: ...


class ProgressReporter(Protocol):
    """Sink for extraction progress; a context manager over the live display."""

    def __enter__(self) -> Self: ...
    def __exit__(self, *exc: object) -> None: ...
    def add_archive(self, name: str, size: int) -> int: ...
    def update(self, handle: int, completed: int) -> None: ...
    def finish(self, handle: int, *, ok: bool) -> None: ...


@dataclass(frozen=True, slots=True)
class ExtractOptions:
    """Knobs for an extraction run."""

    jobs: int = 2
    remove: bool = False


@dataclass(frozen=True, slots=True)
class ExtractionResult:
    """Outcome of extracting a single archive."""

    archive: Archive
    exit_code: int

    @property
    def ok(self) -> bool:
        """Whether the archive extracted cleanly."""
        return self.exit_code == 0


@dataclass(frozen=True, slots=True)
class ExtractionSummary:
    """What a whole run did, for the caller to report on."""

    archives: list[Archive]
    skipped: list[Archive]
    succeeded: list[Archive]
    failed: list[Archive]


@dataclass
class ExtractionState:
    """Ledger of archives already extracted, for resuming a run."""

    path: Path
    completed: dict[str, int] = field(default_factory=dict)

    @classmethod
    def load(cls, path: Path) -> ExtractionState:
        """Load the ledger at ``path``, or start an empty one.

        Args:
            path: Location of the JSON ledger.

        Returns:
            The loaded (or fresh) state.
        """
        if not path.exists():
            return cls(path=path)
        raw = json.loads(path.read_text(encoding="utf-8")).get("completed", {})
        completed = {str(name): int(size) for name, size in raw.items()}
        return cls(path=path, completed=completed)

    def is_done(self, archive: Archive) -> bool:
        """Return whether ``archive`` was already extracted at its current size."""
        return self.completed.get(archive.name) == archive.size

    def mark_done(self, archive: Archive) -> None:
        """Record ``archive`` as extracted and persist the ledger."""
        self.completed[archive.name] = archive.size
        payload = {"completed": dict(sorted(self.completed.items()))}
        self.path.write_text(json.dumps(payload, indent=2), encoding="utf-8")


def build_remote_command(remote_archive: PurePosixPath, remote_target: PurePosixPath) -> str:
    """Build the remote shell command that extracts one archive.

    Args:
        remote_archive: The archive's path on the NAS.
        remote_target: Directory on the NAS to extract into.

    Returns:
        A shell command safe to hand to the remote shell.
    """
    archive = shlex.quote(str(remote_archive))
    target = shlex.quote(str(remote_target))
    return f"mkdir -p {target} && dd if={archive} bs=8M status=progress | tar -xz -C {target}"


def _pump_progress(stream: IO[bytes], on_bytes: OnBytes) -> None:
    """Parse ``dd status=progress`` output, reporting each byte count seen.

    ``dd`` rewrites its status line with carriage returns, so we split on
    carriage returns and newlines rather than reading whole lines.
    """
    tail = b""
    while chunk := stream.read(_CHUNK):
        segments = re.split(rb"[\r\n]", tail + chunk)
        tail = segments.pop()
        for segment in segments:
            if match := _BYTES_RE.search(segment):
                on_bytes(int(match.group(1)))
    if match := _BYTES_RE.search(tail):
        on_bytes(int(match.group(1)))


def _spawn(argv: list[str]) -> _Process:
    return subprocess.Popen(  # noqa: S603 - argv is ssh + a command built from trusted mount config
        argv,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.PIPE,
        bufsize=0,
    )


def run_ssh_extract(
    host: str,
    remote_archive: PurePosixPath,
    remote_target: PurePosixPath,
    on_bytes: OnBytes,
    *,
    popen: Callable[[list[str]], _Process] = _spawn,
) -> int:
    """Extract one archive on ``host`` over SSH, feeding progress to ``on_bytes``.

    Args:
        host: SSH destination (the NAS).
        remote_archive: The archive's path on the NAS.
        remote_target: Directory on the NAS to extract into.
        on_bytes: Called with the running compressed-byte count.
        popen: Process factory (injectable for tests).

    Returns:
        The remote pipeline's exit code (i.e. ``tar``'s).

    Raises:
        RuntimeError: If the SSH process exposes no stderr pipe (should not happen).
    """
    argv = ssh_argv(host, build_remote_command(remote_archive, remote_target))
    with popen(argv) as process:
        stream = process.stderr
        if stream is None:  # pragma: no cover - stderr=PIPE always yields a stream
            msg = "ssh process did not provide a stderr pipe"
            raise RuntimeError(msg)
        _pump_progress(stream, on_bytes)
        return process.wait()


def make_ssh_extractor(remote: RemoteLocation) -> Extractor:
    """Build the default SSH-backed extractor for a target directory.

    Args:
        remote: The target directory's location on the NAS.

    Returns:
        An :data:`Extractor` that extracts archives into ``remote``.
    """

    def extract(archive: Archive, on_bytes: OnBytes) -> int:
        return run_ssh_extract(remote.host, remote.path / archive.name, remote.path, on_bytes)

    return extract


@dataclass
class _Track:
    name: str
    total: int
    completed: int = 0


class RichProgressReporter:
    """Live Rich display: one bar per archive plus an overall bar."""

    def __init__(self, total: int, done: int) -> None:
        self._total = total
        self._done = done
        self._lock = threading.Lock()
        self._tracks: dict[int, _Track] = {}
        self._progress = Progress(
            TextColumn("[bold blue]{task.description}"),
            BarColumn(bar_width=None),
            TaskProgressColumn(),
            DownloadColumn(),
            TransferSpeedColumn(),
            TimeRemainingColumn(compact=True),
            console=console,
        )
        self._overall = TaskID(0)

    def __enter__(self) -> Self:
        self._progress.start()
        self._overall = self._progress.add_task("Overall", total=self._total, completed=self._done)
        return self

    def __exit__(self, *_exc: object) -> None:
        self._progress.stop()

    def add_archive(self, name: str, size: int) -> int:
        handle = int(self._progress.add_task(name, total=size))
        self._tracks[handle] = _Track(name=name, total=size)
        return handle

    def update(self, handle: int, completed: int) -> None:
        with self._lock:
            track = self._tracks[handle]
            delta = completed - track.completed
            track.completed = completed
        self._progress.update(TaskID(handle), completed=completed)
        self._progress.update(self._overall, advance=delta)

    def finish(self, handle: int, *, ok: bool) -> None:
        track = self._tracks[handle]
        if ok:
            self.update(handle, track.total)
        mark = "[green]✓" if ok else "[red]✗"
        self._progress.update(TaskID(handle), description=f"{mark} {track.name}")


def extract_all(
    archives: list[Archive],
    extractor: Extractor,
    reporter: ProgressReporter,
    state: ExtractionState,
    options: ExtractOptions,
) -> list[ExtractionResult]:
    """Extract every not-yet-done archive, concurrently, updating ``reporter``.

    Args:
        archives: All archives in the target (done ones are skipped).
        extractor: How to extract a single archive.
        reporter: Live progress sink (already entered).
        state: Resume ledger; updated as archives complete.
        options: Concurrency and archive-removal settings.

    Returns:
        One result per archive actually attempted this run.
    """
    pending = [archive for archive in archives if not state.is_done(archive)]

    def work(archive: Archive) -> ExtractionResult:
        handle = reporter.add_archive(archive.name, archive.size)
        exit_code = extractor(archive, lambda seen: reporter.update(handle, seen))
        result = ExtractionResult(archive=archive, exit_code=exit_code)
        reporter.finish(handle, ok=result.ok)
        return result

    results: list[ExtractionResult] = []
    with ThreadPoolExecutor(max_workers=options.jobs) as pool:
        futures = [pool.submit(work, archive) for archive in pending]
        for future in as_completed(futures):
            result = future.result()
            results.append(result)
            if result.ok:
                state.mark_done(result.archive)
                logger.info("Extracted %s", result.archive.name)
                if options.remove:
                    result.archive.path.unlink()
                    logger.info("Removed %s", result.archive.name)
            else:
                logger.error("FAILED %s (exit %d)", result.archive.name, result.exit_code)
    return results


def run(
    target: Path,
    *,
    options: ExtractOptions,
    reporter_factory: Callable[[int, int], ProgressReporter] = RichProgressReporter,
    extractor_factory: Callable[[RemoteLocation], Extractor] = make_ssh_extractor,
) -> ExtractionSummary:
    """Extract the takeout in ``target`` on the NAS it is mounted from.

    Args:
        target: Local (NFS) folder holding the ``*.tgz`` archives.
        options: Concurrency and archive-removal settings.
        reporter_factory: Builds the progress reporter from (total, done) bytes.
        extractor_factory: Builds the per-archive extractor from the NAS location.

    Returns:
        A summary of what was skipped, extracted and failed.
    """
    mount = find_mount_for(target, read_mounts())
    remote = resolve_remote(target, mount)
    logger.info("Target %s maps to %s:%s on the NAS", target, remote.host, remote.path)
    check_ssh(mount.host)

    archives = discover(target)
    if not archives:
        return ExtractionSummary(archives=[], skipped=[], succeeded=[], failed=[])

    state = ExtractionState.load(target / STATE_FILENAME)
    skipped = [archive for archive in archives if state.is_done(archive)]
    if skipped:
        logger.info("Resuming: %d of %d archives already extracted", len(skipped), len(archives))

    total = sum(archive.size for archive in archives)
    done = sum(archive.size for archive in skipped)
    reporter = reporter_factory(total, done)
    with reporter:
        results = extract_all(archives, extractor_factory(remote), reporter, state, options)

    return ExtractionSummary(
        archives=archives,
        skipped=skipped,
        succeeded=[result.archive for result in results if result.ok],
        failed=[result.archive for result in results if not result.ok],
    )
