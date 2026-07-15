from __future__ import annotations

import pytest

from negative_space.pairing import (
    is_image,
    is_video,
    motion_still,
    pair_directory,
    sidecar_candidates,
)


@pytest.mark.parametrize(
    ("name", "kind"),
    [
        ("photo.JPG", "image"),
        ("clip.HEIC", "image"),
        ("movie.MP4", "video"),
        ("live.MOV", "video"),
        ("pixel.MP", "video"),
        ("notes.txt", "other"),
        ("no_extension", "other"),
    ],
)
def test_extension_classification(name: str, kind: str) -> None:
    assert is_image(name) == (kind == "image")
    assert is_video(name) == (kind == "video")


@pytest.mark.parametrize(
    ("name", "expected"),
    [
        ("IMG_1.jpg.supplemental-metadata.json", ["IMG_1.jpg"]),
        ("IMG_1.jpg.supplemental-metad.json", ["IMG_1.jpg"]),  # truncated
        ("IMG_1.jpg.supplement.json", ["IMG_1.jpg"]),  # heavily truncated
        # duplicate marker -> the "(N)" media first, base as fallback
        ("IMG_1.jpg.supplemental-metadata(1).json", ["IMG_1(1).jpg", "IMG_1.jpg"]),
        ("PXL_2.MP.jpg.supplemental-met.json", ["PXL_2.MP.jpg"]),  # motion still sidecar
        ("metadata.json", []),  # album metadata, not a sidecar
        ("IMG_1.jpg", []),  # a media file
        ("shared_album_comments.json", []),  # root special file
        (".supplemental-metadata.json", []),  # no media prefix
    ],
)
def test_sidecar_candidates(name: str, expected: list[str]) -> None:
    assert sidecar_candidates(name) == expected


def test_motion_still_same_base_rule() -> None:
    stems = {"mvimg_x": "MVIMG_x.jpg"}
    assert motion_still("MVIMG_x.MP4", stems) == "MVIMG_x.jpg"


def test_motion_still_named_after_whole_video_rule() -> None:
    stems = {"pxl_x.mp": "PXL_x.MP.jpg"}
    assert motion_still("PXL_x.MP", stems) == "PXL_x.MP.jpg"


def test_motion_still_standalone_video_returns_none() -> None:
    assert motion_still("VID.mp4", {"other": "other.jpg"}) is None


def test_pair_directory_full_folder() -> None:
    names = [
        # plain still + sidecar
        "IMG_1.jpg",
        "IMG_1.jpg.supplemental-metadata.json",
        # still with a duplicate (N) sidecar -> the non-(N) one is chosen
        "COLOR.jpg",
        "COLOR.jpg.supplemental-metadata.json",
        "COLOR.jpg.supplemental-metadata(1).json",
        # MVIMG motion photo: same-base video half
        "MVIMG_2.jpg",
        "MVIMG_2.jpg.supplemental-metadata.json",
        "MVIMG_2.MP4",
        # PXL motion photo: still named after the whole video
        "PXL_3.MP.jpg",
        "PXL_3.MP.jpg.supplemental-me.json",  # truncated sidecar
        "PXL_3.MP",
        # standalone (real) video with its own sidecar
        "VID_4.mp4",
        "VID_4.mp4.supplemental-metadata.json",
        # album metadata + an orphan sidecar
        "metadata.json",
        "GHOST.jpg.supplemental-metadata.json",
    ]

    result = pair_directory(names)
    by_name = {entry.name: entry for entry in result.entries}

    # Motion-photo video halves are flagged with their still.
    assert {entry.name for entry in result.motion_videos} == {"MVIMG_2.MP4", "PXL_3.MP"}
    assert by_name["MVIMG_2.MP4"].motion_still == "MVIMG_2.jpg"
    assert by_name["PXL_3.MP"].motion_still == "PXL_3.MP.jpg"
    # Motion halves carry no sidecar of their own.
    assert by_name["MVIMG_2.MP4"].sidecar is None

    # Keepers: stills + the standalone video (not the motion halves).
    assert {entry.name for entry in result.keepers} == {
        "IMG_1.jpg",
        "COLOR.jpg",
        "MVIMG_2.jpg",
        "PXL_3.MP.jpg",
        "VID_4.mp4",
    }

    # Sidecars resolved, including truncated names and the standalone video.
    assert by_name["IMG_1.jpg"].sidecar == "IMG_1.jpg.supplemental-metadata.json"
    assert by_name["PXL_3.MP.jpg"].sidecar == "PXL_3.MP.jpg.supplemental-me.json"
    assert by_name["VID_4.mp4"].sidecar == "VID_4.mp4.supplemental-metadata.json"
    # Duplicate (N) sidecar: the clean one wins.
    assert by_name["COLOR.jpg"].sidecar == "COLOR.jpg.supplemental-metadata.json"

    assert result.orphan_sidecars == ("GHOST.jpg.supplemental-metadata.json",)
    assert result.other == ("metadata.json",)


def test_pair_directory_resolves_numbered_duplicate_to_numbered_media() -> None:
    # Takeout puts "(1)" on the JSON of the base name, but it belongs to the
    # "(1)" media file -- the base keeps its own clean sidecar.
    names = [
        "COLOR.jpg",
        "COLOR.jpg.supplemental-metadata.json",
        "COLOR(1).jpg",
        "COLOR.jpg.supplemental-metadata(1).json",
    ]

    result = pair_directory(names)
    by_name = {entry.name: entry for entry in result.entries}

    assert by_name["COLOR.jpg"].sidecar == "COLOR.jpg.supplemental-metadata.json"
    assert by_name["COLOR(1).jpg"].sidecar == "COLOR.jpg.supplemental-metadata(1).json"
    assert result.orphan_sidecars == ()


def test_pair_directory_prefers_least_truncated_sidecar() -> None:
    # Two non-"(N)" sidecars for one still: the longer (least truncated) wins.
    names = [
        "A.jpg",
        "A.jpg.supplement.json",
        "A.jpg.supplemental-metadata.json",
    ]

    result = pair_directory(names)

    (entry,) = result.entries
    assert entry.sidecar == "A.jpg.supplemental-metadata.json"
    assert result.orphan_sidecars == ()
