from __future__ import annotations

import datetime

import pytest

from negative_space.exif import Capture
from negative_space.metadata import (
    MetadataSource,
    PhotoMetadata,
    Resolved,
    _coord,
    _people,
    _timestamp,
    parse_sidecar,
    resolve_directory,
)
from negative_space.pairing import pair_directory

_TS = "1408262445"  # 2014-08-17 08:00:45 UTC
_WHEN = datetime.datetime(2014, 8, 17, 8, 0, 45, tzinfo=datetime.UTC)


# --- pure parse helpers ----------------------------------------------------


@pytest.mark.parametrize(
    ("node", "expected"),
    [
        ({"timestamp": _TS}, _WHEN),
        ({"timestamp": 1408262445}, _WHEN),
        ({"timestamp": "not-a-number"}, None),
        ({"timestamp": [1]}, None),  # wrong type
        ({}, None),  # no timestamp key
        ("not-a-dict", None),
    ],
)
def test_timestamp(node: object, expected: datetime.datetime | None) -> None:
    assert _timestamp(node) == expected


@pytest.mark.parametrize(
    ("node", "expected"),
    [
        ({"latitude": 51.5, "longitude": -0.12}, (51.5, -0.12)),
        ({"latitude": 0.0, "longitude": 0.0}, None),  # no fix
        ({"latitude": "x", "longitude": 1}, None),  # non-numeric
        ({"latitude": 5}, None),  # missing longitude
        ("not-a-dict", None),
    ],
)
def test_coord(node: object, expected: tuple[float, float] | None) -> None:
    assert _coord(node) == expected


@pytest.mark.parametrize(
    ("node", "expected"),
    [
        ([{"name": "Emma"}, {"name": "Ben"}], ("Emma", "Ben")),
        ([{"noname": 1}, {"name": 5}, "x"], ()),  # skip malformed entries
        ("not-a-list", ()),
    ],
)
def test_people(node: object, expected: tuple[str, ...]) -> None:
    assert _people(node) == expected


def test_parse_sidecar_full() -> None:
    data = {
        "photoTakenTime": {"timestamp": _TS},
        "geoData": {"latitude": 51.5, "longitude": -0.12},
        "people": [{"name": "Emma"}],
        "description": "  a caption  ",
    }

    assert parse_sidecar(data) == PhotoMetadata(
        taken_at=_WHEN,
        latitude=51.5,
        longitude=-0.12,
        people=("Emma",),
        description="a caption",
    )


def test_parse_sidecar_gps_falls_back_to_exif() -> None:
    data = {
        "geoData": {"latitude": 0.0, "longitude": 0.0},
        "geoDataExif": {"latitude": 40.0, "longitude": -3.0},
        "description": 123,  # non-string is ignored
    }

    metadata = parse_sidecar(data)
    assert (metadata.latitude, metadata.longitude) == (40.0, -3.0)
    assert not metadata.description


def test_parse_sidecar_empty() -> None:
    assert parse_sidecar({}) == PhotoMetadata(taken_at=None)


# --- resolution ladder -----------------------------------------------------


def test_resolve_directory_walks_every_source() -> None:
    names = [
        "A.jpg",
        "A.jpg.supplemental-metadata.json",  # own sidecar
        "A-edited.jpg",  # inherits from A.jpg
        "B.jpg",  # no sidecar -> EXIF
        "C.jpg",  # no sidecar, no EXIF -> UNRESOLVED
        "D.jpg",
        "D.jpg.supplemental-metadata.json",  # sidecar present but unreadable -> EXIF
        "E.jpg",  # original with no sidecar
        "E-edited.jpg",  # parent lacks a sidecar -> falls through to UNRESOLVED
        "M.jpg",
        "M.jpg.supplemental-metadata.json",
        "M.MP4",  # motion video -> dropped, never resolved
    ]
    pairing = pair_directory(names)
    sidecars: dict[str, dict[str, object]] = {
        "A.jpg.supplemental-metadata.json": {"photoTakenTime": {"timestamp": _TS}},
        "M.jpg.supplemental-metadata.json": {"photoTakenTime": {"timestamp": _TS}},
    }
    captures = {"B.jpg": Capture(taken_at=_WHEN, latitude=1.0, longitude=2.0)}

    resolved = resolve_directory(pairing, load_sidecar=sidecars.get, read_exif=captures.get)
    by_name = {item.name: item for item in resolved}

    assert by_name["A.jpg"].source is MetadataSource.SIDECAR
    assert by_name["A.jpg"].metadata.taken_at == _WHEN

    assert by_name["A-edited.jpg"].source is MetadataSource.INHERITED
    assert by_name["A-edited.jpg"].via == "A.jpg"
    assert by_name["A-edited.jpg"].metadata.taken_at == _WHEN

    assert by_name["B.jpg"].source is MetadataSource.EXIF
    assert by_name["B.jpg"].metadata.latitude == pytest.approx(1.0)

    assert by_name["C.jpg"].source is MetadataSource.UNRESOLVED
    assert not by_name["C.jpg"].has_date

    assert by_name["D.jpg"].source is MetadataSource.UNRESOLVED  # sidecar unreadable, no EXIF
    assert by_name["E-edited.jpg"].source is MetadataSource.UNRESOLVED

    assert "M.MP4" not in by_name  # motion video is not a keeper
    assert by_name["M.jpg"].source is MetadataSource.SIDECAR


def test_resolved_inherit_when_parent_sidecar_unreadable() -> None:
    # Parent has a sidecar file, but the loader can't read it -> not inherited.
    pairing = pair_directory(["F.jpg", "F.jpg.supplemental-metadata.json", "F-edited.jpg"])

    resolved = resolve_directory(
        pairing,
        load_sidecar=lambda _name: None,
        read_exif={"F-edited.jpg": Capture(taken_at=_WHEN)}.get,
    )
    by_name = {item.name: item for item in resolved}

    assert by_name["F.jpg"].source is MetadataSource.UNRESOLVED
    assert by_name["F-edited.jpg"] == Resolved(
        "F-edited.jpg",
        PhotoMetadata(taken_at=_WHEN),
        MetadataSource.EXIF,
    )
