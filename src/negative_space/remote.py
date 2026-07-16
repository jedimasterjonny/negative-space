"""Deploy and locate exiftool on the NAS.

The organise step rewrites photo metadata with exiftool, which must run on the
NAS so the files never leave it. exiftool is pure Perl, so this checks Perl is
present (the Synology Perl package) and installs the official exiftool release
if it is missing, then returns the command used to invoke it.
"""

from __future__ import annotations

import shlex
import subprocess  # noqa: S404 - only runs ssh with a script built from a quoted install dir
from typing import TYPE_CHECKING

from negative_space.nas import NasError, ssh_argv

if TYPE_CHECKING:
    from collections.abc import Callable

_PERL_MISSING_CODE = 3


def _ensure_script(install_dir: str) -> str:
    directory = shlex.quote(install_dir)
    return (
        "set -e\n"
        f"DIR={directory}\n"
        'mkdir -p "$DIR"\n'
        "command -v perl >/dev/null 2>&1 || { echo PERL_MISSING >&2; exit 3; }\n"
        'ET=$(ls "$DIR"/Image-ExifTool-*/exiftool 2>/dev/null | head -1)\n'
        'if [ -z "$ET" ]; then\n'
        "  VER=$(curl -fsSL https://exiftool.org/ver.txt)\n"
        '  URL="https://sourceforge.net/projects/exiftool/files/Image-ExifTool-$VER.tar.gz/download"\n'
        '  curl -fsSL -o "$DIR/exiftool.tar.gz" "$URL"\n'
        '  tar xzf "$DIR/exiftool.tar.gz" -C "$DIR"\n'
        '  rm -f "$DIR/exiftool.tar.gz"\n'
        '  ET=$(ls "$DIR"/Image-ExifTool-*/exiftool 2>/dev/null | head -1)\n'
        "fi\n"
        'perl "$ET" -ver >/dev/null\n'
        'printf "perl %s\\n" "$ET"\n'
    )


def ensure_exiftool(
    host: str,
    install_dir: str,
    *,
    runner: Callable[..., subprocess.CompletedProcess[str]] = subprocess.run,
) -> str:
    """Ensure exiftool is installed on ``host`` and return how to invoke it.

    Args:
        host: SSH destination (the NAS).
        install_dir: Directory on the NAS to install exiftool into.
        runner: Callable used to run the SSH command (injectable for tests).

    Returns:
        The command prefix that runs exiftool on the NAS, e.g.
        ``perl /volume1/.../Image-ExifTool-13.59/exiftool``.

    Raises:
        NasError: If Perl is missing or exiftool cannot be deployed.
    """
    result = runner(
        ssh_argv(host, _ensure_script(install_dir)),
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        check=False,
    )
    if result.returncode == _PERL_MISSING_CODE:
        msg = (
            "Perl is not installed on the NAS; exiftool needs it. "
            "Install the 'Perl' package from Synology Package Center and retry."
        )
        raise NasError(msg)
    if result.returncode != 0:
        detail = (result.stderr or "").strip() or f"exit code {result.returncode}"
        msg = f"Could not deploy exiftool to the NAS ({detail})."
        raise NasError(msg)
    return result.stdout.strip()
