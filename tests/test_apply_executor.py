from __future__ import annotations

import sys
from typing import TYPE_CHECKING

from negative_space._apply_executor import apply_manifest, digest, move, photo_flags

if TYPE_CHECKING:
    from pathlib import Path

# ``true`` ignores its arguments and exits 0 — a stand-in for exiftool so the
# executor's hardlink/move logic runs without a real exiftool present.
_FAKE_EXIFTOOL = ["true"]


def _photo(src: str, dst: str, **extra: object) -> dict:
    return {"kind": "photo", "src": src, "dst": dst, "mtime": 1_569_584_843, "taken": "x", **extra}


def test_photo_flags_strips_and_writes_date_without_gps() -> None:
    flags = photo_flags({"taken": "2019:09:27 11:47:23"})

    assert flags[0] == "-overwrite_original_in_place"  # in place, so a hardlink can stand in
    assert "-all=" in flags
    assert "-DateTimeOriginal=2019:09:27 11:47:23" in flags
    assert not any(flag.startswith("-GPS") for flag in flags)


def test_photo_flags_encodes_gps_hemispheres() -> None:
    flags = photo_flags({"taken": "x", "lat": -33.9, "lng": -18.4})

    assert "-GPSLatitude=33.9" in flags
    assert "-GPSLatitudeRef=S" in flags
    assert "-GPSLongitude=18.4" in flags
    assert "-GPSLongitudeRef=W" in flags


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


def test_apply_manifest_handles_every_kind(tmp_path: Path) -> None:
    (tmp_path / "photo.HEIC").write_bytes(b"\xff\xd8\xffphoto")  # JPEG named .HEIC
    (tmp_path / "video.mp4").write_bytes(b"video")
    (tmp_path / "no-date.png").write_bytes(b"undated")
    (tmp_path / "motion.mp4").write_bytes(b"motion")
    (tmp_path / "kept.jpg").write_bytes(b"same")
    (tmp_path / "dup.jpg").write_bytes(b"same")
    (tmp_path / "kept2.jpg").write_bytes(b"one")
    (tmp_path / "not-really-dup.jpg").write_bytes(b"two")

    out = tmp_path / "library"
    manifest = [
        {"kind": "duplicate", "src": str(tmp_path / "dup.jpg"), "kept": str(tmp_path / "kept.jpg")},
        {
            "kind": "duplicate",
            "src": str(tmp_path / "not-really-dup.jpg"),
            "kept": str(tmp_path / "kept2.jpg"),
        },
        {"kind": "motion", "src": str(tmp_path / "motion.mp4")},
        {"kind": "motion", "src": str(tmp_path / "already-gone.mp4")},  # skip: already deleted
        _photo(str(tmp_path / "photo.HEIC"), str(out / "2019" / "shot.jpg"), lat=51.5, lng=-0.1),
        {
            "kind": "video",
            "src": str(tmp_path / "video.mp4"),
            "dst": str(out / "2019" / "clip.mp4"),
            "mtime": 1_569_584_843,
        },
        {
            "kind": "undated",
            "src": str(tmp_path / "no-date.png"),
            "dst": str(out / "unsorted" / "x.png"),
        },
        {"kind": "mystery", "src": str(tmp_path / "kept.jpg")},  # unrecognised: no-op ("ok")
    ]

    counts = apply_manifest(manifest, _FAKE_EXIFTOOL, str(tmp_path / "links"))

    assert counts == {
        "duplicate:ok": 1,
        "duplicate:differs": 1,
        "motion:ok": 1,
        "motion:skip": 1,
        "photo:ok": 1,
        "video:ok": 1,
        "undated:ok": 1,
        "mystery:ok": 1,
    }
    # The dated photo (named .HEIC) was moved to its .jpg destination.
    assert (out / "2019" / "shot.jpg").read_bytes() == b"\xff\xd8\xffphoto"
    assert (out / "2019" / "clip.mp4").read_bytes() == b"video"
    assert (out / "unsorted" / "x.png").read_bytes() == b"undated"
    assert not (tmp_path / "motion.mp4").exists()
    assert not (tmp_path / "dup.jpg").exists()  # verified duplicate deleted
    assert (tmp_path / "not-really-dup.jpg").exists()  # mismatched "duplicate" kept


def test_apply_manifest_batches_photos_across_the_chunk_size(tmp_path: Path) -> None:
    # More than one chunk of photos exercises the flush-when-full path.
    out = tmp_path / "lib"
    manifest = []
    for i in range(300):  # _CHUNK is 256
        (tmp_path / f"p{i}.jpg").write_bytes(b"x")
        manifest.append(_photo(str(tmp_path / f"p{i}.jpg"), str(out / f"{i}.jpg")))

    counts = apply_manifest(manifest, _FAKE_EXIFTOOL, str(tmp_path / "links"))

    assert counts == {"photo:ok": 300}
    assert len(list(out.iterdir())) == 300


def test_apply_manifest_skips_already_applied_photo(tmp_path: Path) -> None:
    out = tmp_path / "lib" / "x.jpg"
    out.parent.mkdir(parents=True)
    out.write_bytes(b"already here")  # source gone, destination present -> done
    manifest = [_photo(str(tmp_path / "gone.jpg"), str(out))]

    counts = apply_manifest(manifest, _FAKE_EXIFTOOL, str(tmp_path / "links"))

    assert counts == {"photo:skip": 1}
    assert out.read_bytes() == b"already here"


def test_apply_manifest_moves_unrewritable_photos_to_unsorted(tmp_path: Path) -> None:
    # ``false`` fails every rewrite; the photos are moved to unsorted/ as-is
    # rather than lost. Two share a name -> the second gets a " (2)" suffix.
    (tmp_path / "a").mkdir()
    (tmp_path / "b").mkdir()
    (tmp_path / "a" / "IMG.jpg").write_bytes(b"one")
    (tmp_path / "b" / "IMG.jpg").write_bytes(b"two")
    uns = tmp_path / "lib" / "unsorted"
    manifest = [
        _photo(
            str(tmp_path / "a" / "IMG.jpg"),
            str(tmp_path / "lib" / "x.jpg"),
            unsorted=str(uns / "IMG.jpg"),
        ),
        _photo(
            str(tmp_path / "b" / "IMG.jpg"),
            str(tmp_path / "lib" / "y.jpg"),
            unsorted=str(uns / "IMG.jpg"),
        ),
    ]

    counts = apply_manifest(manifest, ["false"], str(tmp_path / "links"))

    assert counts == {"photo:unsorted": 2}
    assert (uns / "IMG.jpg").exists()
    assert (uns / "IMG (2).jpg").exists()  # collision-renamed, not clobbered
    assert not (tmp_path / "a" / "IMG.jpg").exists()  # moved, not left behind


def test_apply_manifest_errors_when_the_unsorted_move_also_fails(tmp_path: Path) -> None:
    # Rewrite fails and the unsorted destination is unreachable (its parent is a
    # file, not a directory), so this is a genuine error and the file stays put.
    (tmp_path / "IMG.jpg").write_bytes(b"x")
    (tmp_path / "blocker").write_bytes(b"")  # a file where a directory is needed
    manifest = [
        _photo(
            str(tmp_path / "IMG.jpg"),
            str(tmp_path / "lib" / "x.jpg"),
            unsorted=str(tmp_path / "blocker" / "sub" / "IMG.jpg"),
        )
    ]

    counts = apply_manifest(manifest, ["false"], str(tmp_path / "links"))

    assert counts == {"photo:error": 1}
    assert (tmp_path / "IMG.jpg").exists()  # left in place when it can't be moved


def test_apply_manifest_falls_back_to_per_file_on_batch_failure(tmp_path: Path) -> None:
    # A fake exiftool that fails the batch (which carries "-@") but succeeds each
    # single-file retry: the fallback should still apply every photo.
    fake = tmp_path / "fake.py"
    fake.write_text("import sys; sys.exit(1 if '-@' in sys.argv else 0)", encoding="utf-8")
    exiftool = [sys.executable, str(fake)]
    (tmp_path / "a.jpg").write_bytes(b"a")
    (tmp_path / "b.jpg").write_bytes(b"b")
    out = tmp_path / "lib"
    manifest = [_photo(str(tmp_path / n), str(out / n)) for n in ("a.jpg", "b.jpg")]

    counts = apply_manifest(manifest, exiftool, str(tmp_path / "links"))

    assert counts == {"photo:ok": 2}
    assert (out / "a.jpg").exists()


def test_apply_manifest_records_a_drop_error(tmp_path: Path) -> None:
    # A directory can't be hashed, so verifying this "duplicate" raises OSError.
    a_dir = tmp_path / "a_dir"
    a_dir.mkdir()
    manifest = [{"kind": "duplicate", "src": str(a_dir), "kept": str(a_dir)}]

    counts = apply_manifest(manifest, _FAKE_EXIFTOOL, str(tmp_path / "links"))

    assert counts == {"duplicate:error": 1}


def test_apply_manifest_reports_progress(tmp_path: Path) -> None:
    for name in ("a.mp4", "b.mp4", "c.mp4"):
        (tmp_path / name).write_bytes(b"x")
    manifest = [{"kind": "motion", "src": str(tmp_path / n)} for n in ("a.mp4", "b.mp4", "c.mp4")]
    seen: list[tuple[int, int]] = []

    apply_manifest(
        manifest, _FAKE_EXIFTOOL, str(tmp_path / "links"), lambda d, t: seen.append((d, t)), 2
    )

    assert seen == [(2, 3), (3, 3)]  # a tick every 2 ops, and always one at the end


def test_apply_manifest_clears_stale_links(tmp_path: Path) -> None:
    links = tmp_path / "links"
    links.mkdir()
    (links / "l0.jpg").write_bytes(b"stale")  # left by an interrupted run

    apply_manifest([], _FAKE_EXIFTOOL, str(links))

    assert list(links.iterdir()) == []
