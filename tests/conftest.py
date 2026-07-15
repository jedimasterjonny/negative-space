import socket
from typing import Final, NoReturn

import pytest

_REAL_SOCKET: Final[type[socket.socket]] = socket.socket


class NetworkBlockedError(RuntimeError):
    """Raised when test code attempts to open a network socket."""


def _blocked_socket(*_args: object, **_kwargs: object) -> NoReturn:
    msg = (
        "Network access is blocked in tests. Mock the call (e.g. with respx) "
        "or request the `allow_socket` fixture for this test."
    )
    raise NetworkBlockedError(msg)


@pytest.fixture(autouse=True)
def _block_network(monkeypatch: pytest.MonkeyPatch) -> None:
    """Block ``socket.socket`` for every test; tripwire for unmocked network calls."""
    monkeypatch.setattr(socket, "socket", _blocked_socket)


@pytest.fixture
def allow_socket(monkeypatch: pytest.MonkeyPatch) -> None:
    """Opt-out of the network block for a single test that genuinely needs sockets."""
    monkeypatch.setattr(socket, "socket", _REAL_SOCKET)
