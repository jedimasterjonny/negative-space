from __future__ import annotations

import shutil
import subprocess  # noqa: S404 - only used to build CompletedProcess doubles in tests
from pathlib import Path, PurePosixPath

import pytest

from negative_space.nas import (
    NasError,
    NfsMount,
    check_ssh,
    find_mount_for,
    parse_mounts,
    read_mounts,
    resolve_remote,
    ssh_argv,
)

_MOUNTS = (
    "sysfs /sys sysfs rw 0 0\n"
    "administratum:/volume1/scriptorum /nfs/scriptorum nfs4 rw,noatime 0 0\n"
    "192.168.1.225:/volume1/media /nfs/media nfs rw 0 0\n"
    "badline\n"
    "nodevicecolon /mnt/x nfs rw 0 0\n"
    r"administratum:/volume1/a\040b /nfs/escaped nfs4 rw 0 0" + "\n"
    r"h:/e /nfs/wei\xyz nfs rw 0 0" + "\n"
)


def _mount(mount_point: str, export: str = "/volume1/scriptorum", host: str = "nas") -> NfsMount:
    return NfsMount(host=host, export=PurePosixPath(export), mount_point=Path(mount_point))


def test_parse_mounts_keeps_only_remote_nfs_mounts() -> None:
    mounts = {str(mount.mount_point): mount for mount in parse_mounts(_MOUNTS)}

    # sysfs (not nfs), "badline" (too short) and "nodevicecolon" (no host:) dropped.
    assert set(mounts) == {"/nfs/scriptorum", "/nfs/media", "/nfs/escaped", r"/nfs/wei\xyz"}
    assert mounts["/nfs/scriptorum"].host == "administratum"
    assert str(mounts["/nfs/scriptorum"].export) == "/volume1/scriptorum"


def test_parse_mounts_unescapes_octal_and_leaves_unknown_escapes() -> None:
    mounts = {str(mount.mount_point): mount for mount in parse_mounts(_MOUNTS)}

    # \040 -> space in the export path.
    assert str(mounts["/nfs/escaped"].export) == "/volume1/a b"
    # \xyz is not a known escape, so the backslash is left as-is.
    assert str(mounts[r"/nfs/wei\xyz"].mount_point) == r"/nfs/wei\xyz"


def test_read_mounts_reads_from_a_file(tmp_path: Path) -> None:
    table = tmp_path / "mounts"
    table.write_text("administratum:/volume1/scriptorum /nfs/scriptorum nfs4 rw 0 0\n")

    mounts = read_mounts(source=table)

    assert len(mounts) == 1
    assert mounts[0].host == "administratum"


def test_find_mount_for_picks_the_deepest_containing_mount() -> None:
    shallow = _mount("/nfs")
    deep = _mount("/nfs/scriptorum")
    target = Path("/nfs/scriptorum/photos-export")

    assert find_mount_for(target, [shallow, deep]) is deep
    assert find_mount_for(target, [deep, shallow]) is deep  # order-independent


def test_find_mount_for_matches_the_mount_point_itself() -> None:
    deep = _mount("/nfs/scriptorum")

    assert find_mount_for(Path("/nfs/scriptorum"), [deep]) is deep


def test_find_mount_for_raises_when_not_on_an_nfs_mount() -> None:
    with pytest.raises(NasError, match="not on an NFS mount"):
        find_mount_for(Path("/home/jonny/local"), [_mount("/nfs/scriptorum")])


def test_resolve_remote_maps_local_path_to_the_nas() -> None:
    mount = _mount("/nfs/scriptorum", export="/volume1/scriptorum", host="administratum")

    remote = resolve_remote(Path("/nfs/scriptorum/photos-export"), mount)

    assert remote.host == "administratum"
    assert str(remote.path) == "/volume1/scriptorum/photos-export"


def test_ssh_argv_uses_an_absolute_ssh_and_batch_mode(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(shutil, "which", lambda _name: "/usr/bin/ssh")

    assert ssh_argv("nas", "true") == ["/usr/bin/ssh", "-o", "BatchMode=yes", "nas", "true"]


def test_ssh_argv_raises_when_no_ssh_client(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(shutil, "which", lambda _name: None)

    with pytest.raises(NasError, match="ssh"):
        ssh_argv("nas", "true")


def test_check_ssh_accepts_a_reachable_host(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(shutil, "which", lambda _name: "/usr/bin/ssh")

    def ok(argv: list[str], **_kwargs: object) -> subprocess.CompletedProcess[str]:
        return subprocess.CompletedProcess(argv, 0)

    check_ssh("nas", runner=ok)  # must not raise


def test_check_ssh_reports_stderr_detail(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(shutil, "which", lambda _name: "/usr/bin/ssh")

    def denied(argv: list[str], **_kwargs: object) -> subprocess.CompletedProcess[str]:
        return subprocess.CompletedProcess(argv, 255, stderr="Permission denied\n")

    with pytest.raises(NasError, match="Permission denied"):
        check_ssh("nas", runner=denied)


def test_check_ssh_falls_back_to_exit_code(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(shutil, "which", lambda _name: "/usr/bin/ssh")

    def failed(argv: list[str], **_kwargs: object) -> subprocess.CompletedProcess[str]:
        return subprocess.CompletedProcess(argv, 7, stderr="")

    with pytest.raises(NasError, match="exit code 7"):
        check_ssh("nas", runner=failed)
