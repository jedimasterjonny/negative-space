from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

from typer.testing import CliRunner

from negative_space import __main__
from negative_space.archives import Archive
from negative_space.cli import app
from negative_space.extract import ExtractionSummary, ExtractOptions
from negative_space.nas import NasError

if TYPE_CHECKING:
    import pytest

runner = CliRunner()

# Box-drawing characters Rich uses for rules and error panels. Stripping them
# lets us match wrapped, bordered text without caring where line breaks fall.
_BOX = str.maketrans(dict.fromkeys("│╭╮╰╯─", " "))


def _flatten(text: str) -> str:
    # Collapse Rich output to a single space-separated line for matching.
    return " ".join(text.translate(_BOX).split())


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


def test_organise_reports_singular_counts(tmp_path: Path) -> None:
    (tmp_path / "Photos").mkdir()
    (tmp_path / "index.html").touch()

    result = runner.invoke(app, ["organise", str(tmp_path)])

    assert result.exit_code == 0
    output = _flatten(result.stdout)
    assert "Found 1 top-level directory and 1 top-level file." in output
    assert "Folder looks good." in output
    assert "Reading top-level entries" not in output  # debug hidden without -v


def test_organise_reports_plural_counts(tmp_path: Path) -> None:
    (tmp_path / "PhotosA").mkdir()
    (tmp_path / "PhotosB").mkdir()

    result = runner.invoke(app, ["organise", str(tmp_path)])

    assert result.exit_code == 0
    assert "Found 2 top-level directories and 0 top-level files." in _flatten(result.stdout)


def test_organise_verbose_flag_emits_debug_detail(tmp_path: Path) -> None:
    (tmp_path / "Photos").mkdir()

    result = runner.invoke(app, ["organise", "--verbose", str(tmp_path)])

    assert result.exit_code == 0
    assert "Reading top-level entries" in _flatten(result.stdout)


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
