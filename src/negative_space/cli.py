"""Command-line entry point for organising a Google Photos takeout.

The takeout typically lives on a NAS, so the CLI is deliberately verbose: it
narrates each step and prefers directory reads that don't fan out into a stat
per entry, keeping chatter across the network to a minimum.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Annotated

import typer

from negative_space.console import configure_logging, console, logger

app = typer.Typer(
    name="negative-space",
    help="Organise a Google Photos takeout stored on a NAS.",
    add_completion=False,
    no_args_is_help=True,
    rich_markup_mode="rich",
)

TargetArgument = Annotated[
    Path,
    typer.Argument(
        exists=True,
        file_okay=False,
        dir_okay=True,
        readable=True,
        resolve_path=True,
        show_default=False,
        metavar="TARGET",
        help="Path to the Google Photos takeout folder (e.g. a NAS mount).",
    ),
]

VerboseOption = Annotated[
    bool,
    typer.Option(
        "--verbose",
        "-v",
        help="Emit debug-level detail about every step.",
    ),
]


def _summarise_entries(target: Path) -> tuple[int, int]:
    """Count immediate children of ``target`` with a single directory read.

    Uses :func:`os.scandir` so the directory type is taken from the directory
    listing itself rather than a per-entry ``stat`` call — one network round
    trip instead of one per child.

    Args:
        target: Directory to inspect.

    Returns:
        A ``(directories, files)`` tuple counting immediate children. Anything
        that is not a directory (files, symlinks, special files) counts as a
        file.
    """
    directories = 0
    files = 0
    with os.scandir(target) as entries:
        for entry in entries:
            if entry.is_dir(follow_symlinks=False):
                directories += 1
            else:
                files += 1
    return directories, files


@app.command()
def organise(target: TargetArgument, *, verbose: VerboseOption = False) -> None:
    """Organise the Google Photos takeout at TARGET.

    This first step validates the folder and reports what it finds; the
    reorganisation itself is built out in later commands.
    """
    configure_logging(verbose=verbose)

    console.rule("[bold]negative-space")
    logger.info("Target takeout folder: %s", target)
    logger.debug("Reading top-level entries (single directory scan)...")

    directories, files = _summarise_entries(target)
    logger.info(
        "Found %d top-level %s and %d top-level %s.",
        directories,
        "directory" if directories == 1 else "directories",
        files,
        "file" if files == 1 else "files",
    )
    logger.info("Folder looks good. Organising steps will be added next.")
