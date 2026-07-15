from __future__ import annotations

import io
import json
import shutil
import subprocess  # noqa: S404 - only used to monkeypatch the default process factory
import threading
from pathlib import Path, PurePosixPath
from typing import TYPE_CHECKING

from negative_space.archives import Archive
from negative_space.extract import (
    STATE_FILENAME,
    ExtractionState,
    ExtractOptions,
    RichProgressReporter,
    build_remote_command,
    extract_all,
    make_ssh_extractor,
    run,
    run_ssh_extract,
)
from negative_space.nas import NfsMount, RemoteLocation

if TYPE_CHECKING:
    from typing import IO, Self

    import pytest

    from negative_space.extract import Extractor, OnBytes


class RecordingReporter:
    """A ProgressReporter that just records calls, for asserting on."""

    def __init__(self, total: int = 0, done: int = 0) -> None:
        self.total = total
        self.done = done
        self.entered = False
        self.exited = False
        self.added: list[tuple[str, int]] = []
        self.updates: list[tuple[int, int]] = []
        self.finished: list[tuple[int, bool]] = []
        self._lock = threading.Lock()
        self._next = 0

    def __enter__(self) -> Self:
        self.entered = True
        return self

    def __exit__(self, *_exc: object) -> None:
        self.exited = True

    def add_archive(self, name: str, size: int) -> int:
        with self._lock:
            handle = self._next
            self._next += 1
            self.added.append((name, size))
        return handle

    def update(self, handle: int, completed: int) -> None:
        with self._lock:
            self.updates.append((handle, completed))

    def finish(self, handle: int, *, ok: bool) -> None:
        with self._lock:
            self.finished.append((handle, ok))


class _FakeProcess:
    def __init__(self, stream: IO[bytes], returncode: int) -> None:
        self.stderr: IO[bytes] | None = stream
        self._rc = returncode

    def wait(self) -> int:
        return self._rc

    def __enter__(self) -> Self:
        return self

    def __exit__(self, *_exc: object) -> None:
        return None


def _archive(path: Path, size: int) -> Archive:
    return Archive(path=path, size=size)


def _fake_extractor(codes: dict[str, int] | None = None) -> Extractor:
    codes = codes or {}

    def extract(archive: Archive, on_bytes: OnBytes) -> int:
        on_bytes(archive.size)
        return codes.get(archive.name, 0)

    return extract


# --- command building ------------------------------------------------------


def test_build_remote_command_quotes_paths_and_pipes_to_tar() -> None:
    command = build_remote_command(
        PurePosixPath("/volume1/s/a b.tgz"),
        PurePosixPath("/volume1/s"),
    )

    assert command == (
        "mkdir -p /volume1/s && dd if='/volume1/s/a b.tgz' bs=8M status=progress "
        "| tar -xz -C /volume1/s"
    )


# --- run_ssh_extract (exercises the dd-progress parser) --------------------


def test_run_ssh_extract_parses_progress_and_returns_zero(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(shutil, "which", lambda _name: "/usr/bin/ssh")
    seen: list[int] = []
    argvs: list[list[str]] = []

    def fake_popen(argv: list[str]) -> _FakeProcess:
        argvs.append(argv)
        return _FakeProcess(io.BytesIO(b"512 bytes copied\r1024 bytes copied\nrecords\n"), 0)

    code = run_ssh_extract(
        "nas",
        PurePosixPath("/v/a.tgz"),
        PurePosixPath("/v"),
        seen.append,
        popen=fake_popen,
    )

    assert code == 0
    assert seen == [512, 1024]  # 'records' line ignored
    assert argvs[0][0] == "/usr/bin/ssh"
    assert "dd if=/v/a.tgz" in argvs[0][-1]


def test_run_ssh_extract_reads_trailing_line_and_returns_exit_code(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(shutil, "which", lambda _name: "/usr/bin/ssh")
    seen: list[int] = []

    def fake_popen(_argv: list[str]) -> _FakeProcess:
        # No trailing newline: the final byte count lives in the leftover tail.
        return _FakeProcess(io.BytesIO(b"records in\n4096 bytes copied"), 2)

    code = run_ssh_extract(
        "nas",
        PurePosixPath("/v/a.tgz"),
        PurePosixPath("/v"),
        seen.append,
        popen=fake_popen,
    )

    assert code == 2
    assert seen == [4096]


def test_run_ssh_extract_default_factory_spawns_ssh(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(shutil, "which", lambda _name: "/usr/bin/ssh")
    argvs: list[list[str]] = []
    bufsizes: list[object] = []

    def fake_popen(argv: list[str], **kwargs: object) -> _FakeProcess:
        argvs.append(argv)
        bufsizes.append(kwargs.get("bufsize"))
        return _FakeProcess(io.BytesIO(b"100 bytes copied\n"), 0)

    monkeypatch.setattr(subprocess, "Popen", fake_popen)
    seen: list[int] = []

    # No popen= argument, so the default _spawn factory (real subprocess) runs.
    code = run_ssh_extract("nas", PurePosixPath("/v/a.tgz"), PurePosixPath("/v"), seen.append)

    assert code == 0
    assert seen == [100]
    assert argvs[0][:4] == ["/usr/bin/ssh", "-o", "BatchMode=yes", "nas"]
    assert "dd if=/v/a.tgz" in argvs[0][-1]
    assert bufsizes == [0]


def test_make_ssh_extractor_extracts_into_the_remote_dir(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[tuple[str, str, str]] = []

    def fake_run_ssh_extract(
        host: str,
        remote_archive: PurePosixPath,
        remote_target: PurePosixPath,
        on_bytes: OnBytes,
    ) -> int:
        calls.append((host, str(remote_archive), str(remote_target)))
        on_bytes(5)
        return 0

    monkeypatch.setattr("negative_space.extract.run_ssh_extract", fake_run_ssh_extract)
    extractor = make_ssh_extractor(RemoteLocation(host="nas", path=PurePosixPath("/volume1/s")))
    seen: list[int] = []

    code = extractor(_archive(Path("/nfs/s/a.tgz"), 5), seen.append)

    assert code == 0
    assert seen == [5]
    assert calls == [("nas", "/volume1/s/a.tgz", "/volume1/s")]


# --- resume state ----------------------------------------------------------


def test_state_load_missing_file_is_empty(tmp_path: Path) -> None:
    state = ExtractionState.load(tmp_path / "state.json")

    assert state.completed == {}


def test_state_roundtrips_and_matches_on_size(tmp_path: Path) -> None:
    path = tmp_path / "state.json"
    archive = _archive(Path("/x/a.tgz"), 100)

    state = ExtractionState.load(path)
    assert not state.is_done(archive)
    state.mark_done(archive)
    assert state.is_done(archive)

    reloaded = ExtractionState.load(path)
    assert reloaded.completed == {"a.tgz": 100}
    assert reloaded.is_done(archive)
    # A re-downloaded archive of a different size is not considered done.
    assert not reloaded.is_done(_archive(Path("/x/a.tgz"), 101))


# --- extract_all -----------------------------------------------------------


def test_extract_all_skips_done_and_records_successes(tmp_path: Path) -> None:
    archives = []
    for name, size in [("a.tgz", 10), ("b.tgz", 20), ("c.tgz", 30)]:
        path = tmp_path / name
        path.write_bytes(b"x" * size)
        archives.append(_archive(path, size))
    state = ExtractionState.load(tmp_path / STATE_FILENAME)
    state.mark_done(archives[0])
    reporter = RecordingReporter()

    results = extract_all(archives, _fake_extractor(), reporter, state, ExtractOptions(jobs=1))

    assert {result.archive.name for result in results} == {"b.tgz", "c.tgz"}
    assert all(result.ok for result in results)
    assert state.completed == {"a.tgz": 10, "b.tgz": 20, "c.tgz": 30}
    assert {name for name, _ in reporter.added} == {"b.tgz", "c.tgz"}
    assert all(ok for _, ok in reporter.finished)


def test_extract_all_marks_a_failure_without_recording_it_done(tmp_path: Path) -> None:
    good = _archive(tmp_path / "good.tgz", 5)
    bad = _archive(tmp_path / "bad.tgz", 5)
    for archive in (good, bad):
        archive.path.write_bytes(b"x" * 5)
    state = ExtractionState.load(tmp_path / STATE_FILENAME)
    reporter = RecordingReporter()

    results = extract_all(
        [good, bad],
        _fake_extractor({"bad.tgz": 1}),
        reporter,
        state,
        ExtractOptions(jobs=1),
    )

    by_name = {result.archive.name: result for result in results}
    assert by_name["good.tgz"].ok
    assert not by_name["bad.tgz"].ok
    assert state.completed == {"good.tgz": 5}  # failure not persisted
    assert sorted(ok for _, ok in reporter.finished) == [False, True]


def test_extract_all_removes_only_successful_archives(tmp_path: Path) -> None:
    good = _archive(tmp_path / "good.tgz", 5)
    bad = _archive(tmp_path / "bad.tgz", 5)
    for archive in (good, bad):
        archive.path.write_bytes(b"x" * 5)
    state = ExtractionState.load(tmp_path / STATE_FILENAME)

    extract_all(
        [good, bad],
        _fake_extractor({"bad.tgz": 1}),
        RecordingReporter(),
        state,
        ExtractOptions(jobs=1, remove=True),
    )

    assert not good.path.exists()  # removed after clean extraction
    assert bad.path.exists()  # failed extraction keeps the archive


def test_extract_all_runs_multiple_jobs_concurrently(tmp_path: Path) -> None:
    archives = []
    for index in range(4):
        path = tmp_path / f"{index}.tgz"
        path.write_bytes(b"x")
        archives.append(_archive(path, 1))
    state = ExtractionState.load(tmp_path / STATE_FILENAME)

    results = extract_all(
        archives,
        _fake_extractor(),
        RecordingReporter(),
        state,
        ExtractOptions(jobs=2),
    )

    assert len(results) == 4
    assert all(result.ok for result in results)
    assert len(state.completed) == 4


# --- run (top-level orchestration) -----------------------------------------


def _nfs_mount(mount_point: Path) -> NfsMount:
    return NfsMount(
        host="administratum",
        export=PurePosixPath("/volume1/scriptorum"),
        mount_point=mount_point,
    )


def _passthrough_extractor_factory(_remote: RemoteLocation) -> Extractor:
    return _fake_extractor()


def test_run_extracts_all_archives(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    target = tmp_path / "photos-export"
    target.mkdir()
    (target / "t-001.tgz").write_bytes(b"x" * 10)
    (target / "t-002.tgz").write_bytes(b"y" * 20)
    monkeypatch.setattr("negative_space.extract.read_mounts", lambda: [_nfs_mount(tmp_path)])
    monkeypatch.setattr("negative_space.extract.check_ssh", lambda _host: None)
    reporters: list[RecordingReporter] = []

    def reporter_factory(total: int, done: int) -> RecordingReporter:
        reporter = RecordingReporter(total, done)
        reporters.append(reporter)
        return reporter

    summary = run(
        target,
        options=ExtractOptions(jobs=1),
        reporter_factory=reporter_factory,
        extractor_factory=_passthrough_extractor_factory,
    )

    assert {archive.name for archive in summary.succeeded} == {"t-001.tgz", "t-002.tgz"}
    assert summary.failed == []
    assert summary.skipped == []
    assert reporters[0].entered
    assert reporters[0].exited


def test_run_skips_already_extracted_archives(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    target = tmp_path / "photos-export"
    target.mkdir()
    (target / "t-001.tgz").write_bytes(b"x" * 10)
    (target / "t-002.tgz").write_bytes(b"y" * 20)
    (target / STATE_FILENAME).write_text(json.dumps({"completed": {"t-001.tgz": 10}}))
    monkeypatch.setattr("negative_space.extract.read_mounts", lambda: [_nfs_mount(tmp_path)])
    monkeypatch.setattr("negative_space.extract.check_ssh", lambda _host: None)

    summary = run(
        target,
        options=ExtractOptions(jobs=1),
        reporter_factory=RecordingReporter,
        extractor_factory=_passthrough_extractor_factory,
    )

    assert {archive.name for archive in summary.skipped} == {"t-001.tgz"}
    assert {archive.name for archive in summary.succeeded} == {"t-002.tgz"}


def test_run_returns_empty_summary_when_no_archives(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    target = tmp_path / "photos-export"
    target.mkdir()
    monkeypatch.setattr("negative_space.extract.read_mounts", lambda: [_nfs_mount(tmp_path)])
    monkeypatch.setattr("negative_space.extract.check_ssh", lambda _host: None)
    built: list[object] = []

    def reporter_factory(total: int, done: int) -> RecordingReporter:
        built.append((total, done))
        return RecordingReporter(total, done)

    summary = run(
        target,
        options=ExtractOptions(),
        reporter_factory=reporter_factory,
        extractor_factory=_passthrough_extractor_factory,
    )

    assert summary.archives == []
    assert built == []  # no reporter built when there is nothing to do


# --- RichProgressReporter --------------------------------------------------


def test_rich_progress_reporter_tracks_overall_and_per_archive() -> None:
    reporter = RichProgressReporter(total=200, done=0)

    with reporter:
        done_handle = reporter.add_archive("a.tgz", 100)
        reporter.update(done_handle, 50)
        reporter.finish(done_handle, ok=True)
        failed_handle = reporter.add_archive("b.tgz", 100)
        reporter.finish(failed_handle, ok=False)

    assert reporter._tracks[done_handle].completed == 100  # completed to total
    assert reporter._tracks[failed_handle].completed == 0  # failure left as-is
    # Overall (task 0) advanced only by the successful archive.
    assert reporter._progress.tasks[0].completed == 100
