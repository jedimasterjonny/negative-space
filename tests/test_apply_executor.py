from __future__ import annotations

from typing import TYPE_CHECKING

from negative_space import _apply_executor
from negative_space._apply_executor import apply_manifest, digest, move, photo_argv, rewrite

if TYPE_CHECKING:
    from pathlib import Path

    import pytest

# ``true`` ignores its arguments and exits 0 — a stand-in for exiftool so the
# executor's move/mtime logic can be exercised without a real exiftool present.
_FAKE_EXIFTOOL = ["true"]


def test_photo_argv_strips_and_writes_date_without_gps() -> None:
    argv = photo_argv(["perl", "exiftool"], "2019:09:27 11:47:23", None, None, "/p.jpg")

    assert argv[:2] == ["perl", "exiftool"]
    assert "-all=" in argv
    assert "-DateTimeOriginal=2019:09:27 11:47:23" in argv
    assert not any(arg.startswith("-GPS") for arg in argv)
    assert argv[-1] == "/p.jpg"


def test_photo_argv_encodes_gps_hemispheres() -> None:
    # Southern + western hemisphere -> S/W refs, magnitudes positive.
    argv = photo_argv(["exiftool"], "2019:09:27 11:47:23", -33.9, -18.4, "/p.jpg")

    assert "-GPSLatitude=33.9" in argv
    assert "-GPSLatitudeRef=S" in argv
    assert "-GPSLongitude=18.4" in argv
    assert "-GPSLongitudeRef=W" in argv


def test_digest_matches_for_identical_bytes(tmp_path: Path) -> None:
    (tmp_path / "a").write_bytes(b"hello world" * 1000)
    (tmp_path / "b").write_bytes(b"hello world" * 1000)
    (tmp_path / "c").write_bytes(b"different")

    assert digest(str(tmp_path / "a")) == digest(str(tmp_path / "b"))
    assert digest(str(tmp_path / "a")) != digest(str(tmp_path / "c"))


def test_move_creates_parents_and_sets_mtime(tmp_path: Path) -> None:
    src = tmp_path / "src.jpg"
    src.write_bytes(b"x")
    dst = tmp_path / "2019" / "09 - September" / "shot.jpg"

    move(str(src), str(dst), 1_569_584_843.0)

    assert not src.exists()
    assert dst.read_bytes() == b"x"
    assert round(dst.stat().st_mtime) == 1_569_584_843


def test_rewrite_moves_to_destination_before_running_exiftool(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # A JPEG mislabelled ".HEIC": exiftool must see the ".jpg" destination, not
    # the ".HEIC" source, so the move has to happen first.
    src = tmp_path / "IMG.HEIC"
    src.write_bytes(b"\xff\xd8\xffjpeg")
    dst = tmp_path / "out" / "2022" / "shot.jpg"
    seen: dict[str, object] = {}

    def fake_run(argv: list[str], **_kwargs: object) -> None:
        seen["last_arg"] = argv[-1]
        seen["dst_exists_when_called"] = dst.exists()

    monkeypatch.setattr(_apply_executor.subprocess, "run", fake_run)

    rewrite(
        ["exiftool"],
        {
            "src": str(src),
            "dst": str(dst),
            "taken": "2022:08:06 07:40:32",
            "mtime": 1_659_771_632,
            "lat": 52.2,
            "lng": 0.1,
        },
    )

    assert seen["last_arg"] == str(dst)  # exiftool operated on the destination
    assert seen["dst_exists_when_called"] is True  # ...which already existed (moved first)
    assert not src.exists()


def test_apply_manifest_skips_already_applied_moves(tmp_path: Path) -> None:
    # A move whose source is gone and destination is in place is already done.
    out = tmp_path / "library" / "x.jpg"
    out.parent.mkdir(parents=True)
    out.write_bytes(b"already here")
    gone = str(tmp_path / "gone.jpg")
    manifest = [{"kind": "photo", "src": gone, "dst": str(out), "mtime": 1, "taken": "x"}]

    counts = apply_manifest(manifest, _FAKE_EXIFTOOL)

    assert counts == {"photo:skip": 1}
    assert out.read_bytes() == b"already here"  # untouched


def test_apply_manifest_records_exiftool_failure(tmp_path: Path) -> None:
    # ``false`` exits non-zero, standing in for an exiftool that refuses the file.
    (tmp_path / "bad.jpg").write_bytes(b"\xff\xd8\xff")
    manifest = [
        {
            "kind": "photo",
            "src": str(tmp_path / "bad.jpg"),
            "dst": str(tmp_path / "out" / "bad.jpg"),
            "mtime": 1,
            "taken": "2019:09:27 11:47:23",
        },
    ]

    counts = apply_manifest(manifest, ["false"])

    assert counts == {"photo:error": 1}


def test_apply_manifest_reports_progress(tmp_path: Path) -> None:
    (tmp_path / "a.mp4").write_bytes(b"a")
    (tmp_path / "b.mp4").write_bytes(b"b")
    (tmp_path / "c.mp4").write_bytes(b"c")
    manifest = [{"kind": "motion", "src": str(tmp_path / n)} for n in ("a.mp4", "b.mp4", "c.mp4")]
    seen: list[tuple[int, int]] = []

    apply_manifest(manifest, _FAKE_EXIFTOOL, lambda done, total: seen.append((done, total)), 2)

    # A tick every 2 ops, and always one at the end.
    assert seen == [(2, 3), (3, 3)]


def test_apply_manifest_handles_every_kind(tmp_path: Path) -> None:
    # One file of each kind, plus a duplicate whose bytes DON'T match its keeper.
    (tmp_path / "photo.jpg").write_bytes(b"photo")
    (tmp_path / "video.mp4").write_bytes(b"video")
    (tmp_path / "no-date.png").write_bytes(b"undated")
    (tmp_path / "motion.mp4").write_bytes(b"motion")
    (tmp_path / "kept.jpg").write_bytes(b"same")
    (tmp_path / "dup.jpg").write_bytes(b"same")
    (tmp_path / "kept2.jpg").write_bytes(b"one")
    (tmp_path / "not-really-dup.jpg").write_bytes(b"two")
    (tmp_path / "mystery.bin").write_bytes(b"?")

    out = tmp_path / "library"
    manifest = [
        {
            "kind": "photo",
            "src": str(tmp_path / "photo.jpg"),
            "dst": str(out / "2019" / "09 - September" / "shot.jpg"),
            "mtime": 1_569_584_843,
            "taken": "2019:09:27 11:47:23",
            "lat": 51.5,
            "lng": -0.1,
        },
        {
            "kind": "video",
            "src": str(tmp_path / "video.mp4"),
            "dst": str(out / "2019" / "09 - September" / "clip.mp4"),
            "mtime": 1_569_584_843,
        },
        {
            "kind": "undated",
            "src": str(tmp_path / "no-date.png"),
            "dst": str(out / "unsorted" / "no-date.png"),
        },
        {"kind": "motion", "src": str(tmp_path / "motion.mp4")},
        {"kind": "duplicate", "src": str(tmp_path / "dup.jpg"), "kept": str(tmp_path / "kept.jpg")},
        {
            "kind": "duplicate",
            "src": str(tmp_path / "not-really-dup.jpg"),
            "kept": str(tmp_path / "kept2.jpg"),
        },
        {"kind": "motion", "src": str(tmp_path / "already-gone.mp4")},  # skip: already deleted
        {"kind": "mystery", "src": str(tmp_path / "mystery.bin")},  # unrecognised: no-op
    ]

    counts = apply_manifest(manifest, _FAKE_EXIFTOOL)

    assert counts == {
        "photo:ok": 1,
        "video:ok": 1,
        "undated:ok": 1,
        "motion:ok": 1,
        "duplicate:ok": 1,
        "duplicate:differs": 1,
        "motion:skip": 1,
        "mystery:ok": 1,
    }
    # An unrecognised op touches nothing.
    assert (tmp_path / "mystery.bin").read_bytes() == b"?"
    # Placements moved into the library.
    assert (out / "2019" / "09 - September" / "shot.jpg").read_bytes() == b"photo"
    assert (out / "2019" / "09 - September" / "clip.mp4").read_bytes() == b"video"
    assert (out / "unsorted" / "no-date.png").read_bytes() == b"undated"
    # Motion + verified duplicate deleted; the mismatched "duplicate" is preserved.
    assert not (tmp_path / "motion.mp4").exists()
    assert not (tmp_path / "dup.jpg").exists()
    assert (tmp_path / "not-really-dup.jpg").exists()
