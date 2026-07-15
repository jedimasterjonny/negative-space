from __future__ import annotations

import pytest

from negative_space.pairing import (
    edited_original,
    expected_sidecars,
    is_image,
    is_video,
    motion_still,
    pair_directory,
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
        # short name: the full, untruncated sidecar
        ("IMG_1.jpg", ["IMG_1.jpg.supplemental-metadata.json"]),
        # long name: truncated to 51 chars, cutting even ".jpg" down to ".jp"
        (
            "PXL_20201119_165135173.PORTRAIT-02.ORIGINAL.jpg",
            ["PXL_20201119_165135173.PORTRAIT-02.ORIGINAL.jp.json"],
        ),
        # numbered duplicate: its own name first, then the base name's "(N)" sidecar
        (
            "COLOR(1).jpg",
            [
                "COLOR(1).jpg.supplemental-metadata.json",
                "COLOR.jpg.supplemental-metadata(1).json",
            ],
        ),
    ],
)
def test_expected_sidecars(name: str, expected: list[str]) -> None:
    assert expected_sidecars(name) == expected


def test_expected_sidecars_numbered_duplicate_appends_after_truncation() -> None:
    # The base sidecar is truncated to the limit first, then "(N)" is appended --
    # so the "(N)" name can legitimately exceed the limit.
    cands = expected_sidecars("PXL_20201104_072546224(1).jpg")
    assert "PXL_20201104_072546224.jpg.supplemental-metada(1).json" in cands


def test_motion_still_same_base_rule() -> None:
    stems = {"mvimg_x": "MVIMG_x.jpg"}
    assert motion_still("MVIMG_x.MP4", stems) == "MVIMG_x.jpg"


def test_motion_still_named_after_whole_video_rule() -> None:
    stems = {"pxl_x.mp": "PXL_x.MP.jpg"}
    assert motion_still("PXL_x.MP", stems) == "PXL_x.MP.jpg"


def test_motion_still_standalone_video_returns_none() -> None:
    assert motion_still("VID.mp4", {"other": "other.jpg"}) is None


_LONG = "PXL_20201105_160816198.PORTRAIT-02.ORIGINAL"


@pytest.mark.parametrize(
    ("name", "media", "expected"),
    [
        ("IMG_1-edited.jpg", {"IMG_1.jpg", "IMG_1-edited.jpg"}, "IMG_1.jpg"),
        # long name: "-edited" was truncated to "-edi" to fit the limit
        (f"{_LONG}-edi.jpg", {f"{_LONG}.jpg", f"{_LONG}-edi.jpg"}, f"{_LONG}.jpg"),
        # a short "-e" ending is not a truncated "-edited"
        ("cafe-e.jpg", {"cafe.jpg", "cafe-e.jpg"}, None),
        # edited copy whose original is not present
        ("LONE-edited.jpg", {"LONE-edited.jpg"}, None),
        ("holiday.jpg", {"holiday.jpg"}, None),  # not an edit
        ("no_extension", set(), None),  # nothing to strip
    ],
)
def test_edited_original(name: str, media: set[str], expected: str | None) -> None:
    assert edited_original(name, media) == expected


def test_pair_directory_links_edited_copy_to_its_original() -> None:
    names = [
        "IMG_1.jpg",
        "IMG_1.jpg.supplemental-metadata.json",
        "IMG_1-edited.jpg",  # an edit: no sidecar of its own
        "RANDOM.jpg",  # no sidecar, not an edit
    ]

    result = pair_directory(names)
    by_name = {entry.name: entry for entry in result.entries}

    assert by_name["IMG_1-edited.jpg"].sidecar is None
    assert by_name["IMG_1-edited.jpg"].original == "IMG_1.jpg"
    assert by_name["IMG_1.jpg"].original is None  # has its own sidecar
    assert by_name["RANDOM.jpg"].original is None  # no sidecar, but not an edit


def test_pair_directory_full_folder() -> None:
    names = [
        # plain still + sidecar
        "IMG_1.jpg",
        "IMG_1.jpg.supplemental-metadata.json",
        # MVIMG motion photo: same-base video half
        "MVIMG_2.jpg",
        "MVIMG_2.jpg.supplemental-metadata.json",
        "MVIMG_2.MP4",
        # PXL motion photo: still named after the whole video
        "PXL_3.MP.jpg",
        "PXL_3.MP.jpg.supplemental-metadata.json",
        "PXL_3.MP",
        # standalone (real) video with its own sidecar
        "VID_4.mp4",
        "VID_4.mp4.supplemental-metadata.json",
        # album metadata + an orphan sidecar (its media is gone)
        "metadata.json",
        "GHOST.jpg.supplemental-metadata.json",
    ]

    result = pair_directory(names)
    by_name = {entry.name: entry for entry in result.entries}

    # Motion-photo video halves are flagged with their still.
    assert {entry.name for entry in result.motion_videos} == {"MVIMG_2.MP4", "PXL_3.MP"}
    assert by_name["MVIMG_2.MP4"].motion_still == "MVIMG_2.jpg"
    assert by_name["PXL_3.MP"].motion_still == "PXL_3.MP.jpg"
    assert by_name["MVIMG_2.MP4"].sidecar is None  # motion halves carry no sidecar

    # Keepers: stills + the standalone video (not the motion halves).
    assert {entry.name for entry in result.keepers} == {
        "IMG_1.jpg",
        "MVIMG_2.jpg",
        "PXL_3.MP.jpg",
        "VID_4.mp4",
    }

    assert by_name["IMG_1.jpg"].sidecar == "IMG_1.jpg.supplemental-metadata.json"
    assert by_name["PXL_3.MP.jpg"].sidecar == "PXL_3.MP.jpg.supplemental-metadata.json"
    assert by_name["VID_4.mp4"].sidecar == "VID_4.mp4.supplemental-metadata.json"

    assert result.orphan_sidecars == ("GHOST.jpg.supplemental-metadata.json",)
    assert result.other == ("metadata.json",)


def test_pair_directory_matches_hard_truncated_sidecar() -> None:
    # A long media name: the sidecar is truncated so far that ".jpg" -> ".jp"
    # and "supplemental-metadata" vanishes entirely.
    media = "PXL_20201119_165135173.PORTRAIT-02.ORIGINAL.jpg"
    sidecar = "PXL_20201119_165135173.PORTRAIT-02.ORIGINAL.jp.json"

    result = pair_directory([media, sidecar])

    (entry,) = result.entries
    assert entry.sidecar == sidecar
    assert result.orphan_sidecars == ()


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
