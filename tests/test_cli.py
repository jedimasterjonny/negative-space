from __future__ import annotations

import datetime
import re
from pathlib import Path, PurePosixPath
from typing import TYPE_CHECKING, cast

from typer.testing import CliRunner

from negative_space import __main__
from negative_space.apply import ApplyOutcome
from negative_space.archives import Archive
from negative_space.cli import app
from negative_space.extract import ExtractionSummary, ExtractOptions
from negative_space.metadata import MetadataSource, PhotoMetadata
from negative_space.nas import NasError, NfsMount
from negative_space.plan import Drop, Keeper

if TYPE_CHECKING:
    import pytest

    from negative_space.plan import LibraryPlan

runner = CliRunner()

# Box-drawing characters Rich uses for rules and error panels. Stripping them
# lets us match wrapped, bordered text without caring where line breaks fall.
_BOX = str.maketrans(dict.fromkeys("│╭╮╰╯─", " "))
# ANSI escape sequences: Rich emits colour when the shared console has been put
# in terminal mode by another test, so strip them to match styling-agnostically.
_ANSI = re.compile(r"\x1b\[[0-9;?]*[a-zA-Z]")


def _flatten(text: str) -> str:
    # Collapse Rich output to a single space-separated line for matching.
    return " ".join(_ANSI.sub("", text).translate(_BOX).split())


def _archive(name: str, size: int = 10) -> Archive:
    return Archive(path=Path("/nfs/scriptorum/photos-export") / name, size=size)


def _summary(
    *,
    archives: list[Archive],
    skipped: list[Archive] | None = None,
    succeeded: list[Archive] | None = None,
    failed: list[Archive] | None = None,
) -> ExtractionSummary:
    return ExtractionSummary(
        archives=archives,
        skipped=skipped or [],
        succeeded=succeeded or [],
        failed=failed or [],
    )


# --- organise --------------------------------------------------------------


def test_organise_dry_run_reports_the_plan(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    mount = NfsMount(host="nas", export=PurePosixPath("/volume1/scriptorum"), mount_point=tmp_path)
    when = datetime.datetime(2019, 9, 27, 11, 47, 23)  # noqa: DTZ001 - naive UTC
    keepers = [
        Keeper(
            tmp_path / "a.jpg",
            is_video=False,
            size=1000,
            extension=".jpg",
            metadata=PhotoMetadata(when),
            source_tag=MetadataSource.SIDECAR,
        ),
    ]
    drops = [Drop(tmp_path / "m.mp4", 2_000_000_000)]

    def fake_scan(_target: Path, **_kwargs: object) -> tuple[list[Keeper], list[Drop]]:
        return keepers, drops

    monkeypatch.setattr("negative_space.cli.read_mounts", lambda: [mount])
    monkeypatch.setattr("negative_space.cli.check_ssh", lambda _host: None)
    monkeypatch.setattr(
        "negative_space.cli.ensure_exiftool", lambda _host, _dir: "perl /x/exiftool"
    )
    monkeypatch.setattr("negative_space.cli.scan", fake_scan)

    result = runner.invoke(app, ["organise", str(tmp_path)])

    assert result.exit_code == 0
    output = _flatten(result.stdout)
    assert "1 keepers" in output
    assert "2.0 GB" in output  # motion videos reclaimed
    assert "September" in output  # planned folder for the dated photo
    assert "sidecar" in output  # metadata-source breakdown
    assert "Dry run" in output


def _setup_nas(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> tuple[list[Keeper], list[Drop]]:
    # Wire up the NAS-facing calls the organise command makes, with a scan that
    # returns one dated photo and one motion-video drop.
    mount = NfsMount(host="nas", export=PurePosixPath("/volume1/scriptorum"), mount_point=tmp_path)
    when = datetime.datetime(2019, 9, 27, 11, 47, 23)  # noqa: DTZ001 - naive UTC
    keepers = [
        Keeper(
            tmp_path / "a.jpg",
            is_video=False,
            size=1000,
            extension=".jpg",
            metadata=PhotoMetadata(when),
            source_tag=MetadataSource.SIDECAR,
        ),
    ]
    drops = [Drop(tmp_path / "m.mp4", 2_000_000_000)]
    monkeypatch.setattr("negative_space.cli.read_mounts", lambda: [mount])
    monkeypatch.setattr("negative_space.cli.check_ssh", lambda _host: None)
    monkeypatch.setattr(
        "negative_space.cli.ensure_exiftool", lambda _host, _dir: "perl /x/exiftool"
    )
    monkeypatch.setattr("negative_space.cli.scan", lambda _target, **_kw: (keepers, drops))
    return keepers, drops


def test_organise_apply_runs_and_reports_results(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _setup_nas(tmp_path, monkeypatch)
    counts = {
        "photo:ok": 80,
        "motion:ok": 27,
        "duplicate:ok": 25,
        "duplicate:differs": 2,
        "video:skip": 3,
        "photo:error": 1,
    }
    captured: dict[str, object] = {}

    def fake_apply(plan: object, **kwargs: object) -> ApplyOutcome:
        captured.update(kwargs)
        return ApplyOutcome(plan=cast("LibraryPlan", plan), counts=counts)

    monkeypatch.setattr("negative_space.cli.run_apply", fake_apply)

    result = runner.invoke(app, ["organise", "--apply", "--yes", str(tmp_path)])

    assert result.exit_code == 0
    output = _flatten(result.stdout)
    assert "Applied 132 operations" in output  # 80 + 27 + 25 ok
    assert "3 already done" in output  # skipped
    assert "not byte-identical" in output  # the 2 duplicates that differed
    assert "failed" in output  # the 1 error
    # Applied into a sibling "-organised" library on the NAS.
    assert captured["output_root"] == "/volume1/scriptorum-organised"
    assert captured["work_dir"] == "/volume1/scriptorum/.negative-space/apply"


def test_organise_apply_clean_run_reports_only_the_total(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _setup_nas(tmp_path, monkeypatch)

    def fake_apply(plan: object, **_kwargs: object) -> ApplyOutcome:
        return ApplyOutcome(plan=cast("LibraryPlan", plan), counts={"photo:ok": 100})

    monkeypatch.setattr("negative_space.cli.run_apply", fake_apply)

    result = runner.invoke(app, ["organise", "--apply", "--yes", str(tmp_path)])

    assert result.exit_code == 0
    output = _flatten(result.stdout)
    assert "Applied 100 operations" in output
    # No skips, mismatches or errors, so none of those lines appear.
    assert "already done" not in output
    assert "not byte-identical" not in output
    assert "failed" not in output


def test_organise_apply_aborts_without_confirmation(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _setup_nas(tmp_path, monkeypatch)
    called = False

    def fake_apply(_plan: object, **_kwargs: object) -> ApplyOutcome:
        nonlocal called
        called = True
        raise AssertionError  # must not run when the user declines

    monkeypatch.setattr("negative_space.cli.run_apply", fake_apply)

    result = runner.invoke(app, ["organise", "--apply", str(tmp_path)], input="n\n")

    assert result.exit_code == 1  # typer.confirm(abort=True) aborts
    assert not called


def test_organise_apply_reports_nas_error(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    _setup_nas(tmp_path, monkeypatch)

    def boom(_plan: object, **_kwargs: object) -> ApplyOutcome:
        message = "apply executor failed on nas (exit 1)"
        raise NasError(message)

    monkeypatch.setattr("negative_space.cli.run_apply", boom)

    result = runner.invoke(app, ["organise", "--apply", "--yes", str(tmp_path)])

    assert result.exit_code == 1
    assert "apply executor failed" in _flatten(result.stdout)


def test_organise_reports_nas_error(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    def boom() -> list[NfsMount]:
        message = "not on an NFS mount"
        raise NasError(message)

    monkeypatch.setattr("negative_space.cli.read_mounts", boom)

    result = runner.invoke(app, ["organise", str(tmp_path)])

    assert result.exit_code == 1
    assert "not on an NFS mount" in _flatten(result.stdout)


def test_organise_missing_target_is_rejected(tmp_path: Path) -> None:
    result = runner.invoke(app, ["organise", str(tmp_path / "does-not-exist")])

    assert result.exit_code == 2
    assert "does not exist" in _flatten(result.stderr)


def test_organise_file_target_is_rejected(tmp_path: Path) -> None:
    photo = tmp_path / "photo.jpg"
    photo.touch()

    result = runner.invoke(app, ["organise", str(photo)])

    assert result.exit_code == 2
    assert "is a file" in _flatten(result.stderr)


def test_organise_without_target_shows_usage_error() -> None:
    result = runner.invoke(app, ["organise"])

    assert result.exit_code == 2
    assert "Missing argument" in _flatten(result.stderr)


# --- extract ---------------------------------------------------------------


def test_extract_passes_options_and_reports_success(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    seen_targets: list[Path] = []
    seen_options: list[ExtractOptions] = []

    def fake_run(target: Path, *, options: ExtractOptions) -> ExtractionSummary:
        seen_targets.append(target)
        seen_options.append(options)
        return _summary(archives=[_archive("a.tgz")], succeeded=[_archive("a.tgz")])

    monkeypatch.setattr("negative_space.cli.run_extraction", fake_run)

    result = runner.invoke(app, ["extract", "-j", "3", "--remove-archives", str(tmp_path)])

    assert result.exit_code == 0
    assert seen_targets == [tmp_path]
    assert seen_options == [ExtractOptions(jobs=3, remove=True)]
    assert "Done: 1 extracted, 0 failed, 0 skipped" in _flatten(result.stdout)


def test_extract_warns_when_no_archives(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    def fake_run(_target: Path, **_kwargs: object) -> ExtractionSummary:
        return _summary(archives=[])

    monkeypatch.setattr("negative_space.cli.run_extraction", fake_run)

    result = runner.invoke(app, ["extract", str(tmp_path)])

    assert result.exit_code == 0
    assert "No .tgz archives found" in _flatten(result.stdout)


def test_extract_reports_nas_error(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    def fake_run(_target: Path, **_kwargs: object) -> ExtractionSummary:
        message = "cannot reach the NAS"
        raise NasError(message)

    monkeypatch.setattr("negative_space.cli.run_extraction", fake_run)

    result = runner.invoke(app, ["extract", str(tmp_path)])

    assert result.exit_code == 1
    assert "cannot reach the NAS" in _flatten(result.stdout)


def test_extract_exits_nonzero_when_an_archive_fails(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    good, bad = _archive("good.tgz"), _archive("bad.tgz")

    def fake_run(_target: Path, **_kwargs: object) -> ExtractionSummary:
        return _summary(archives=[good, bad], succeeded=[good], failed=[bad])

    monkeypatch.setattr("negative_space.cli.run_extraction", fake_run)

    result = runner.invoke(app, ["extract", str(tmp_path)])

    assert result.exit_code == 1
    output = _flatten(result.stdout)
    assert "Done: 1 extracted, 1 failed, 0 skipped" in output
    assert "Did not extract: bad.tgz" in output


def test_module_entrypoint_runs_the_same_app() -> None:
    assert __main__.app is app
