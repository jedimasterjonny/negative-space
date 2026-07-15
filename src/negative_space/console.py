"""Shared Rich console and logging setup for verbose CLI feedback.

The application works against a Google Photos takeout stored on a NAS, so
operations can be slow. Everything routes through a single Rich console and a
timestamped logger so the user always sees forward progress and never wonders
whether the tool has hung.
"""

from __future__ import annotations

import logging
from typing import Final

from rich.console import Console
from rich.logging import RichHandler

#: Application-wide logger. Modules obtain children via ``logging.getLogger``.
LOGGER_NAME: Final = "negative_space"

#: Single console instance shared across the app so output stays coherent.
console: Final = Console()

logger: Final = logging.getLogger(LOGGER_NAME)


def configure_logging(*, verbose: bool) -> None:
    """Configure timestamped Rich logging for the application logger.

    Args:
        verbose: When true, emit ``DEBUG`` detail; otherwise ``INFO``.
    """
    level = logging.DEBUG if verbose else logging.INFO
    handler = RichHandler(
        console=console,
        show_path=False,
        rich_tracebacks=True,
        omit_repeated_times=False,
    )
    handler.setFormatter(logging.Formatter("%(message)s", datefmt="[%X]"))

    logger.setLevel(level)
    logger.handlers.clear()
    logger.addHandler(handler)
    logger.propagate = False
