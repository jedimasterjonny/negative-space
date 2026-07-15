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
from negative_space.extract import ExtractOptions
from negative_space.extract import run as run_extraction
from negative_space.nas import NasError

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

JobsOption = Annotated[
    int,
    typer.Option(
        "--jobs",
        "-j",
        min=1,
        help="How many archives to extract on the NAS at once.",
    ),
]

RemoveArchivesOption = Annotated[
    bool,
    typer.Option(
        "--remove-archives",
        help="Delete each .tgz once it has extracted successfully (default: keep).",
    ),
]


@app.command(
    help=(
        "Extract the takeout .tgz archives in TARGET on the NAS they live on.\n\n"
        "The heavy lifting runs on the NAS over SSH, so nothing but progress text "
        "crosses the network. Progress, throughput and ETA are shown per archive "
        "and overall, and each finished archive is recorded so an interrupted run "
        "resumes instead of starting over."
    ),
)
def extract(
    target: TargetArgument,
    *,
    jobs: JobsOption = 2,
    remove_archives: RemoveArchivesOption = False,
    verbose: VerboseOption = False,
) -> None:
    # No docstring: user-facing help comes from the decorator's ``help=`` so the
    # Args/Raises detail devs would want does not leak into ``--help`` output.
    configure_logging(verbose=verbose)
    console.rule("[bold]negative-space · extract")
    options = ExtractOptions(jobs=jobs, remove=remove_archives)

    try:
        summary = run_extraction(target, options=options)
    except NasError as error:
        # Expected, user-actionable failure — show the message, not a traceback.
        logger.error("%s", error)
        raise typer.Exit(code=1) from error

    if not summary.archives:
        logger.warning("No .tgz archives found in %s.", target)
        return

    logger.info(
        "Done: %d extracted, %d failed, %d skipped (already done).",
        len(summary.succeeded),
        len(summary.failed),
        len(summary.skipped),
    )
    if summary.failed:
        for archive in summary.failed:
            logger.error("Did not extract: %s", archive.name)
        raise typer.Exit(code=1)


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
