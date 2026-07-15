from __future__ import annotations

from typing import TYPE_CHECKING

from negative_space.archives import discover

if TYPE_CHECKING:
    from pathlib import Path


def test_discover_finds_tgz_sorted_by_name(tmp_path: Path) -> None:
    (tmp_path / "takeout-002.tgz").write_bytes(b"bb")
    (tmp_path / "takeout-001.tgz").write_bytes(b"a")
    (tmp_path / "bundle.tar.gz").write_bytes(b"ccc")

    archives = discover(tmp_path)

    assert [archive.name for archive in archives] == [
        "bundle.tar.gz",
        "takeout-001.tgz",
        "takeout-002.tgz",
    ]
    assert [archive.size for archive in archives] == [3, 1, 2]


def test_discover_ignores_non_archives_and_directories(tmp_path: Path) -> None:
    (tmp_path / "takeout-001.tgz").write_bytes(b"a")
    (tmp_path / "notes.txt").write_bytes(b"x")
    (tmp_path / "Takeout").mkdir()  # an extracted tree, not an archive
    (tmp_path / "photos.tgz.part").write_bytes(b"y")  # partial download

    archives = discover(tmp_path)

    assert [archive.name for archive in archives] == ["takeout-001.tgz"]


def test_discover_returns_empty_when_no_archives(tmp_path: Path) -> None:
    (tmp_path / "readme.md").write_bytes(b"hello")

    assert discover(tmp_path) == []
