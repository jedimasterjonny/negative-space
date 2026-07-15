"""Talk to the NAS the takeout lives on.

The dev host mounts the NAS over NFS, so a local path like
``/nfs/scriptorum/photos-export`` actually lives on the NAS as
``administratum:/volume1/scriptorum/photos-export``. Running the heavy work
(decompression, writes) on the NAS itself keeps it off the network entirely.
This module discovers that mapping from ``/proc/mounts`` and provides the SSH
plumbing to run commands there.
"""

from __future__ import annotations

import shutil
import subprocess  # noqa: S404 - only runs ssh with args built from mount config, never a shell
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import TYPE_CHECKING, Final

if TYPE_CHECKING:
    from collections.abc import Callable

_PROC_MOUNTS: Final = Path("/proc/mounts")

# /proc/mounts octal-escapes these bytes in the device/mount-point fields.
_MOUNT_ESCAPES: Final = {"040": " ", "011": "\t", "012": "\n", "134": "\\"}


class NasError(RuntimeError):
    """Raised when the NAS cannot be located or reached."""


@dataclass(frozen=True, slots=True)
class NfsMount:
    """A single NFS mount as reported by ``/proc/mounts``."""

    host: str
    export: PurePosixPath
    mount_point: Path


@dataclass(frozen=True, slots=True)
class RemoteLocation:
    """A path on the NAS, reachable over SSH at ``host``."""

    host: str
    path: PurePosixPath


def _unescape(field: str) -> str:
    out: list[str] = []
    rest = field
    while (index := rest.find("\\")) != -1:
        out.append(rest[:index])
        code = rest[index + 1 : index + 4]
        out.append(_MOUNT_ESCAPES.get(code, "\\"))
        rest = rest[index + 4 :] if code in _MOUNT_ESCAPES else rest[index + 1 :]
    out.append(rest)
    return "".join(out)


def parse_mounts(text: str) -> list[NfsMount]:
    """Parse ``/proc/mounts`` content, keeping only NFS mounts of a remote host.

    Args:
        text: The raw contents of ``/proc/mounts``.

    Returns:
        The NFS mounts found, in the order they appear.
    """
    mounts: list[NfsMount] = []
    for line in text.splitlines():
        fields = line.split()
        if len(fields) < 3:  # noqa: PLR2004 - device, mount point, fs type
            continue
        device, raw_mount, fstype = fields[0], fields[1], fields[2]
        if not fstype.startswith("nfs") or ":" not in device:
            continue
        host, _, export = _unescape(device).partition(":")
        mounts.append(
            NfsMount(
                host=host,
                export=PurePosixPath(export),
                mount_point=Path(_unescape(raw_mount)),
            ),
        )
    return mounts


def read_mounts(source: Path = _PROC_MOUNTS) -> list[NfsMount]:
    """Read and parse the system mount table.

    Args:
        source: File to read the mount table from.

    Returns:
        The NFS mounts currently active.
    """
    return parse_mounts(source.read_text(encoding="utf-8"))


def find_mount_for(path: Path, mounts: list[NfsMount]) -> NfsMount:
    """Return the NFS mount that ``path`` lives on.

    Args:
        path: An absolute local path.
        mounts: Candidate NFS mounts.

    Returns:
        The most specific (deepest) mount that contains ``path``.

    Raises:
        NasError: If no NFS mount contains ``path``.
    """
    best: NfsMount | None = None
    for mount in mounts:
        contains = path == mount.mount_point or mount.mount_point in path.parents
        deeper = best is None or len(mount.mount_point.parts) > len(best.mount_point.parts)
        if contains and deeper:
            best = mount
    if best is None:
        msg = (
            f"{path} is not on an NFS mount, so work cannot be pushed to the NAS. "
            "Point the tool at the takeout on its NAS mount."
        )
        raise NasError(msg)
    return best


def resolve_remote(path: Path, mount: NfsMount) -> RemoteLocation:
    """Translate a local path on ``mount`` to its location on the NAS.

    Args:
        path: An absolute local path inside ``mount``.
        mount: The NFS mount ``path`` belongs to.

    Returns:
        The corresponding path on the NAS host.
    """
    relative = path.relative_to(mount.mount_point)
    return RemoteLocation(host=mount.host, path=mount.export.joinpath(*relative.parts))


def ssh_argv(host: str, remote_command: str) -> list[str]:
    """Build the argv to run ``remote_command`` on ``host`` over SSH.

    Args:
        host: The SSH destination.
        remote_command: A shell command to run on the host.

    Returns:
        The argv list, using an absolute ``ssh`` path.

    Raises:
        NasError: If no ``ssh`` client is on ``PATH``.
    """
    ssh = shutil.which("ssh")
    if ssh is None:
        msg = "No 'ssh' client found on PATH; it is required to drive the NAS."
        raise NasError(msg)
    return [ssh, "-o", "BatchMode=yes", host, remote_command]


def check_ssh(
    host: str,
    *,
    runner: Callable[..., subprocess.CompletedProcess[str]] = subprocess.run,
) -> None:
    """Verify that ``host`` is reachable over SSH without prompting.

    Args:
        host: The SSH destination.
        runner: Callable used to run the probe (injectable for tests).

    Raises:
        NasError: If the SSH probe fails.
    """
    result = runner(
        ssh_argv(host, "true"),
        stdout=subprocess.DEVNULL,
        stderr=subprocess.PIPE,
        text=True,
        check=False,
    )
    if result.returncode != 0:
        detail = (result.stderr or "").strip() or f"exit code {result.returncode}"
        msg = f"Cannot reach {host} over SSH ({detail}). Enable key-based SSH to the NAS."
        raise NasError(msg)
