from pathlib import Path

import pytest
from pydantic import ValidationError

from negative_space.settings import Settings


class _Example(Settings):
    greeting: str


def test_values_are_read_from_dotenv(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    (tmp_path / ".env").write_text("greeting=hello\n")
    monkeypatch.chdir(tmp_path)

    assert _Example().greeting == "hello"


def test_unknown_dotenv_keys_are_rejected(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    (tmp_path / ".env").write_text("greeting=hello\ntypoed_key=1\n")
    monkeypatch.chdir(tmp_path)

    with pytest.raises(ValidationError):
        _Example()
