from __future__ import annotations

import shutil
import subprocess  # noqa: S404 - only builds CompletedProcess doubles in tests

import pytest

from negative_space.nas import NasError
from negative_space.remote import ensure_exiftool


def _process(
    returncode: int, stdout: str = "", stderr: str = ""
) -> subprocess.CompletedProcess[str]:
    return subprocess.CompletedProcess(["ssh"], returncode, stdout=stdout, stderr=stderr)


def test_ensure_exiftool_returns_invocation(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(shutil, "which", lambda _name: "/usr/bin/ssh")
    argvs: list[list[str]] = []

    def runner(argv: list[str], **_kwargs: object) -> subprocess.CompletedProcess[str]:
        argvs.append(argv)
        return _process(0, stdout="perl /vol/.ns/bin/Image-ExifTool-13.59/exiftool\n")

    command = ensure_exiftool("nas", "/vol/my tools/bin", runner=runner)

    assert command == "perl /vol/.ns/bin/Image-ExifTool-13.59/exiftool"
    assert argvs[0][0] == "/usr/bin/ssh"
    assert "https://exiftool.org/ver.txt" in argvs[0][-1]  # deploy step present in the script
    assert "'/vol/my tools/bin'" in argvs[0][-1]  # install dir with a space is shell-quoted


def test_ensure_exiftool_reports_missing_perl(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(shutil, "which", lambda _name: "/usr/bin/ssh")

    def runner(_argv: list[str], **_kwargs: object) -> subprocess.CompletedProcess[str]:
        return _process(3, stderr="PERL_MISSING")

    with pytest.raises(NasError, match="Perl"):
        ensure_exiftool("nas", "/vol/bin", runner=runner)


def test_ensure_exiftool_reports_deploy_failure(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(shutil, "which", lambda _name: "/usr/bin/ssh")

    def runner(_argv: list[str], **_kwargs: object) -> subprocess.CompletedProcess[str]:
        return _process(1, stderr="curl: (6) could not resolve host")

    with pytest.raises(NasError, match="could not resolve host"):
        ensure_exiftool("nas", "/vol/bin", runner=runner)
