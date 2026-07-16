from __future__ import annotations

import datetime
from pathlib import Path, PurePosixPath

from negative_space.apply import build_manifest
from negative_space.metadata import MetadataSource, PhotoMetadata
from negative_space.plan import Drop, Duplicate, LibraryPlan, Placement

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
