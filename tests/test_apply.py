from __future__ import annotations

import datetime
import shutil
import subprocess  # noqa: S404 - only constructs CompletedProcess, never runs a process
from pathlib import Path, PurePosixPath
from typing import TYPE_CHECKING, Self, cast

import pytest

from negative_space import apply as apply_module
from negative_space.apply import (
    ApplyTarget,
    _remote_command,
    build_manifest,
    run_apply,
    run_executor,
    ship,
)
from negative_space.metadata import MetadataSource, PhotoMetadata
from negative_space.nas import NasError, NfsMount
from negative_space.plan import Drop, Duplicate, LibraryPlan, Placement

if TYPE_CHECKING:
    from collections.abc import Sequence

_WHEN = datetime.datetime(2019, 9, 27, 11, 47, 23)  # noqa: DTZ001 - naive UTC by design


def _to_nas(path: Path) -> str:
    # Stand-in for nas.resolve_remote: /nfs/... -> /volume1/...
    return str(path).replace("/nfs", "/volume1")


def _placement(name: str, dest: str, *, video: bool, meta: PhotoMetadata) -> Placement:
    return Placement(
        source=Path("/nfs/export") / name,
        destination=PurePosixPath(dest),
        is_video=video,
        metadata=meta,
        source_tag=MetadataSource.SIDECAR,
    )


def test_build_manifest_lowers_every_op_kind() -> None:
    plan = LibraryPlan(
        placements=(
            _placement(
                "p.jpg",
                "2019/09 - September/2019-09-27 11-47-23.jpg",
                video=False,
                meta=PhotoMetadata(_WHEN, latitude=-33.9, longitude=18.4),
            ),
            _placement(
                "v.mp4",
                "2019/09 - September/2019-09-27 11-47-30.mp4",
                video=True,
                meta=PhotoMetadata(_WHEN.replace(second=30)),
            ),
            _placement("x.png", "unsorted/x.png", video=False, meta=PhotoMetadata(None)),
        ),
        motion_drops=(Drop(Path("/nfs/export/m.mp4"), 10),),
        duplicate_drops=(
            Duplicate(Path("/nfs/export/Album/p.jpg"), 20, Path("/nfs/export/p.jpg")),
        ),
    )

    manifest = build_manifest(plan, output_root="/volume1/library", to_nas=_to_nas)

    assert manifest == [
        # Drops first: the duplicate is verified against its keeper before any
        # placement moves or rewrites that keeper's bytes.
        {
            "kind": "duplicate",
            "src": "/volume1/export/Album/p.jpg",
            "kept": "/volume1/export/p.jpg",
        },
        {"kind": "motion", "src": "/volume1/export/m.mp4"},
        {
            "kind": "photo",
            "src": "/volume1/export/p.jpg",
            "dst": "/volume1/library/2019/09 - September/2019-09-27 11-47-23.jpg",
            "mtime": 1_569_584_843,
            "taken": "2019:09:27 11:47:23",
            "unsorted": "/volume1/library/unsorted/p.jpg",
            "lat": -33.9,
            "lng": 18.4,
        },
        {
            "kind": "video",
            "src": "/volume1/export/v.mp4",
            "dst": "/volume1/library/2019/09 - September/2019-09-27 11-47-30.mp4",
            "mtime": 1_569_584_850,
        },
        {
            "kind": "undated",
            "src": "/volume1/export/x.png",
            "dst": "/volume1/library/unsorted/x.png",
        },
    ]


def test_build_manifest_verifies_duplicates_before_moving_their_keeper() -> None:
    # A keeper that is also some duplicate's ``kept`` copy must be verified
    # against before its own placement relocates (and rewrites) it.
    kept = _placement("p.jpg", "2019/09 - September/x.jpg", video=False, meta=PhotoMetadata(_WHEN))
    plan = LibraryPlan(
        placements=(kept,),
        motion_drops=(),
        duplicate_drops=(
            Duplicate(Path("/nfs/export/Album/p.jpg"), 20, Path("/nfs/export/p.jpg")),
        ),
    )

    kinds = [op["kind"] for op in build_manifest(plan, output_root="/lib", to_nas=_to_nas)]

    assert kinds.index("duplicate") < kinds.index("photo")


def test_build_manifest_moves_dated_bmp_in_unsorted_as_is() -> None:
    # A dated BMP the plan routed to unsorted/ is moved as-is, not rewritten
    # (exiftool can't write BMP metadata).
    plan = LibraryPlan(
        placements=(
            _placement(
                "wallpaper.bmp", "unsorted/wallpaper.bmp", video=False, meta=PhotoMetadata(_WHEN)
            ),
        ),
        motion_drops=(),
        duplicate_drops=(),
    )

    (op,) = build_manifest(plan, output_root="/lib", to_nas=_to_nas)

    assert op["kind"] == "undated"  # move-as-is, despite having a date
    assert op["dst"] == "/lib/unsorted/wallpaper.bmp"
    assert "taken" not in op  # no exiftool rewrite


def test_build_manifest_omits_gps_when_absent() -> None:
    plan = LibraryPlan(
        placements=(
            _placement(
                "p.jpg", "2019/09 - September/x.jpg", video=False, meta=PhotoMetadata(_WHEN)
            ),
        ),
        motion_drops=(),
        duplicate_drops=(),
    )

    (photo,) = build_manifest(plan, output_root="/lib", to_nas=_to_nas)

    assert "lat" not in photo
    assert "lng" not in photo
    assert photo["taken"] == "2019:09:27 11:47:23"


# --- orchestration ---------------------------------------------------------


class _Runner:
    """Records ssh invocations and returns a canned CompletedProcess."""

    def __init__(self, *, stdout: str = "", returncode: int = 0) -> None:
        self.calls: list[tuple[Sequence[str], dict[str, object]]] = []
        self._stdout = stdout
        self._returncode = returncode

    def __call__(self, argv: Sequence[str], **kwargs: object) -> subprocess.CompletedProcess[str]:
        self.calls.append((argv, kwargs))
        return subprocess.CompletedProcess(list(argv), self._returncode, stdout=self._stdout)


def _use_ssh(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(shutil, "which", lambda _name: "/usr/bin/ssh")


def test_remote_command_quotes_the_work_dir() -> None:
    command = _remote_command("/vol/.neg apply", "perl /x/exiftool")

    assert "cd '/vol/.neg apply'" in command  # shlex-quoted (has a space)
    assert command.endswith("python3 _apply_executor.py manifest.json perl /x/exiftool")


def test_ship_creates_dir_then_uploads_executor_and_manifest(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _use_ssh(monkeypatch)
    runner = _Runner()

    ship("nas", "/vol/apply", [{"kind": "motion", "src": "/x"}], runner=runner)

    commands = [call[0][-1] for call in runner.calls]  # ssh_argv puts the command last
    assert commands == [
        "mkdir -p /vol/apply",
        "cat > /vol/apply/_apply_executor.py",
        "cat > /vol/apply/manifest.json",
    ]
    assert "def apply_manifest" in str(runner.calls[1][1]["input"])  # the executor source
    assert runner.calls[2][1]["input"] == '[{"kind": "motion", "src": "/x"}]'


class _FakeProc:
    """Stands in for a streaming subprocess.Popen: iterable stdout + returncode."""

    def __init__(self, lines: list[str], returncode: int) -> None:
        self.stdout = lines
        self.returncode = returncode

    def __enter__(self) -> Self:
        return self

    def __exit__(self, *_args: object) -> bool:
        return False


def _fake_popen(lines: list[str], returncode: int = 0) -> object:
    def factory(_argv: Sequence[str], **_kwargs: object) -> _FakeProc:
        return _FakeProc(lines, returncode)

    return factory


def test_run_executor_tees_to_log_and_returns_counts(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _use_ssh(monkeypatch)
    lines = [
        "PROGRESS 2 4\n",
        "ERROR photo /x/bad.HEIC: not a valid HEIC\n",
        "PROGRESS 4 4\n",
        'RESULT {"photo:ok": 3, "photo:error": 1}\n',
    ]
    monkeypatch.setattr(apply_module.subprocess, "Popen", _fake_popen(lines))
    log = tmp_path / "apply.log"
    ticks: list[tuple[int, int]] = []

    counts = run_executor(
        "nas",
        "/vol/apply",
        "perl /x/exiftool",
        log_path=log,
        on_progress=lambda done, total: ticks.append((done, total)),
    )

    assert counts == {"photo:ok": 3, "photo:error": 1}
    assert ticks == [(2, 4), (4, 4)]  # progress lines drove the callback
    assert "not a valid HEIC" in log.read_text(encoding="utf-8")  # errors captured in the log


def test_run_executor_raises_and_keeps_the_log_on_failure(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _use_ssh(monkeypatch)
    monkeypatch.setattr(apply_module.subprocess, "Popen", _fake_popen(["PROGRESS 1 2\n"], 2))
    log = tmp_path / "apply.log"

    with pytest.raises(NasError, match=f"exit 2.*{log}"):
        run_executor(
            "nas", "/vol/apply", "perl /x/exiftool", log_path=log, on_progress=lambda *_: None
        )

    assert "PROGRESS 1 2" in log.read_text(encoding="utf-8")  # partial log survives


def test_run_apply_builds_ships_runs_and_reads(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    mount = NfsMount(
        host="nas", export=PurePosixPath("/volume1/export"), mount_point=Path("/nfs/export")
    )
    target = ApplyTarget(
        mount=mount,
        exiftool="perl /x/exiftool",
        output_root="/volume1/lib",
        work_dir="/volume1/apply",
    )
    plan = LibraryPlan(
        placements=(
            _placement(
                "p.jpg", "2019/09 - September/x.jpg", video=False, meta=PhotoMetadata(_WHEN)
            ),
        ),
        motion_drops=(),
        duplicate_drops=(),
    )
    seen: dict[str, object] = {}
    monkeypatch.setattr(
        apply_module, "ship", lambda host, wd, manifest: seen.update(shipped=(host, wd, manifest))
    )
    monkeypatch.setattr(
        apply_module,
        "run_executor",
        lambda host, wd, ex, **kw: (
            seen.update(ran=(host, wd, ex), log=kw["log_path"]) or {"photo:ok": 1}
        ),
    )

    outcome = run_apply(plan, target, log_path=tmp_path / "apply.log")

    assert outcome.plan is plan
    assert outcome.counts == {"photo:ok": 1}
    assert seen["ran"] == ("nas", "/volume1/apply", "perl /x/exiftool")
    assert seen["log"] == tmp_path / "apply.log"
    host, work_dir, manifest = cast("tuple[str, str, list[dict[str, str]]]", seen["shipped"])
    assert (host, work_dir) == ("nas", "/volume1/apply")
    # the manifest was built with NAS-local paths under the output root
    assert manifest[0]["dst"] == "/volume1/lib/2019/09 - September/x.jpg"
    assert manifest[0]["src"] == "/volume1/export/p.jpg"
