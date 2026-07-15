from __future__ import annotations

from typing import TYPE_CHECKING

from typer.testing import CliRunner

from negative_space import __main__
from negative_space.cli import app

if TYPE_CHECKING:
    from pathlib import Path

runner = CliRunner()

# Box-drawing characters Rich uses for rules and error panels. Stripping them
# lets us match wrapped, bordered text without caring where line breaks fall.
_BOX = str.maketrans(dict.fromkeys("│╭╮╰╯─", " "))


def _flatten(text: str) -> str:
    # Collapse Rich output to a single space-separated line for matching.
    return " ".join(text.translate(_BOX).split())


def test_reports_singular_counts_for_one_dir_and_one_file(tmp_path: Path) -> None:
    (tmp_path / "Photos").mkdir()
    (tmp_path / "index.html").touch()

    result = runner.invoke(app, [str(tmp_path)])

    assert result.exit_code == 0
    output = _flatten(result.stdout)
    assert "Found 1 top-level directory and 1 top-level file." in output
    assert "Folder looks good." in output
    # Debug detail stays hidden without --verbose.
    assert "Reading top-level entries" not in output


def test_reports_plural_counts(tmp_path: Path) -> None:
    (tmp_path / "PhotosA").mkdir()
    (tmp_path / "PhotosB").mkdir()

    result = runner.invoke(app, [str(tmp_path)])

    assert result.exit_code == 0
    assert "Found 2 top-level directories and 0 top-level files." in _flatten(result.stdout)


def test_verbose_flag_emits_debug_detail(tmp_path: Path) -> None:
    (tmp_path / "Photos").mkdir()

    result = runner.invoke(app, ["--verbose", str(tmp_path)])

    assert result.exit_code == 0
    assert "Reading top-level entries" in _flatten(result.stdout)


def test_missing_target_is_rejected(tmp_path: Path) -> None:
    result = runner.invoke(app, [str(tmp_path / "does-not-exist")])

    assert result.exit_code == 2
    assert "does not exist" in _flatten(result.stderr)


def test_file_target_is_rejected(tmp_path: Path) -> None:
    photo = tmp_path / "photo.jpg"
    photo.touch()

    result = runner.invoke(app, [str(photo)])

    assert result.exit_code == 2
    assert "is a file" in _flatten(result.stderr)


def test_no_target_shows_usage_error() -> None:
    result = runner.invoke(app, [])

    assert result.exit_code == 2
    assert "Missing argument" in _flatten(result.stderr)


def test_module_entrypoint_runs_the_same_app() -> None:
    assert __main__.app is app
