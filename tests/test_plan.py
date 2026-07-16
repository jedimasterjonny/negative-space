from __future__ import annotations

import datetime
import json
from pathlib import Path, PurePosixPath

from negative_space.metadata import MetadataSource, PhotoMetadata
from negative_space.plan import (
    Drop,
    Keeper,
    _load_json,
    _size,
    build_plan,
    scan,
    summarize,
)

_WHEN = datetime.datetime(2019, 9, 27, 11, 47, 23)  # noqa: DTZ001 - naive UTC by design
_SEPT = PurePosixPath("2019", "09 - September")


def _keeper(
    name: str, *, video: bool, when: datetime.datetime | None, tag: MetadataSource
) -> Keeper:
    return Keeper(Path("/t") / name, video, PhotoMetadata(taken_at=when), tag)


def _plan():
    keepers = [
        _keeper("a.jpg", video=False, when=_WHEN, tag=MetadataSource.SIDECAR),
        _keeper("v.mp4", video=True, when=_WHEN.replace(second=30), tag=MetadataSource.SIDECAR),
        _keeper("latest.png", video=False, when=None, tag=MetadataSource.UNRESOLVED),
    ]
    return build_plan(keepers, [Drop(Path("/t/m.mp4"), 1000)])


def test_build_plan_places_and_drops() -> None:
    plan = _plan()
    destinations = {placement.source: placement.destination for placement in plan.placements}

    assert destinations[Path("/t/a.jpg")] == _SEPT / "2019-09-27 11-47-23.jpg"
    assert destinations[Path("/t/v.mp4")] == _SEPT / "2019-09-27 11-47-30.mp4"
    assert destinations[Path("/t/latest.png")] == PurePosixPath("unsorted", "latest.png")
    assert plan.drops == (Drop(Path("/t/m.mp4"), 1000),)


def test_summarize() -> None:
    summary = summarize(_plan())

    assert summary.keepers == 3
    assert (summary.photos, summary.videos, summary.undated) == (2, 1, 1)
    assert summary.by_source == {"sidecar": 2, "unresolved": 1}
    assert summary.by_year == {2019: 2}
    assert summary.motion_count == 1
    assert summary.motion_bytes == 1000


def test_load_json(tmp_path: Path) -> None:
    good = tmp_path / "good.json"
    good.write_text(json.dumps({"a": 1}))
    assert _load_json(good) == {"a": 1}

    bad = tmp_path / "bad.json"
    bad.write_text("{not json")
    assert _load_json(bad) is None

    not_object = tmp_path / "list.json"
    not_object.write_text("[1, 2]")
    assert _load_json(not_object) is None

    assert _load_json(tmp_path / "missing.json") is None


def test_size(tmp_path: Path) -> None:
    present = tmp_path / "f.bin"
    present.write_bytes(b"x" * 42)
    assert _size(present) == 42
    assert _size(tmp_path / "missing.bin") == 0


def test_scan_resolves_and_drops_motion(tmp_path: Path) -> None:
    album = tmp_path / "Album"
    album.mkdir()
    (album / "a.jpg").write_bytes(b"x")
    (album / "a.jpg.supplemental-metadata.json").write_text(
        json.dumps({"photoTakenTime": {"timestamp": "1408262445"}})
    )
    # motion photo: still + same-base video (the video is dropped)
    (album / "m.jpg").write_bytes(b"y")
    (album / "m.jpg.supplemental-metadata.json").write_text(
        json.dumps({"photoTakenTime": {"timestamp": "1408262445"}})
    )
    (album / "m.mp4").write_bytes(b"z" * 100)

    keepers, drops = scan(tmp_path)

    assert {keeper.source.name for keeper in keepers} == {"a.jpg", "m.jpg"}
    assert [drop.source.name for drop in drops] == ["m.mp4"]
    assert drops[0].size == 100

    resolved = next(keeper for keeper in keepers if keeper.source.name == "a.jpg")
    assert resolved.source_tag is MetadataSource.SIDECAR
    assert resolved.metadata.taken_at == datetime.datetime(2014, 8, 17, 8, 0, 45)  # noqa: DTZ001
