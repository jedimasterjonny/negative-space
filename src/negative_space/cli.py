"""Command-line entry point for organising a Google Photos takeout.

The takeout typically lives on a NAS, so the CLI is deliberately verbose: it
narrates each step and prefers directory reads that don't fan out into a stat
per entry, keeping chatter across the network to a minimum.
"""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING, Annotated

import typer
from rich.table import Table

from negative_space.console import configure_logging, console, logger
from negative_space.extract import ExtractOptions
from negative_space.extract import run as run_extraction
from negative_space.nas import NasError, check_ssh, find_mount_for, read_mounts
from negative_space.plan import build_plan, scan, summarize
from negative_space.remote import ensure_exiftool

if TYPE_CHECKING:
    from negative_space.plan import LibraryPlan, PlanSummary

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


ScanJobsOption = Annotated[
    int,
    typer.Option("--jobs", "-j", min=1, help="How many folders to scan at once."),
]


def _render_report(summary: PlanSummary, plan: LibraryPlan) -> None:
    console.print()
    console.print(
        f"[bold]{summary.keepers:,}[/] keepers "
        f"([green]{summary.photos:,}[/] photos, [green]{summary.videos:,}[/] videos)",
    )
    console.print(
        f"[bold]{summary.motion_count:,}[/] motion-photo videos to drop "
        f"([bold]{summary.motion_bytes / 1e9:.1f} GB[/] reclaimed)",
    )
    console.print(
        f"[bold]{summary.duplicate_count:,}[/] duplicate copies to drop "
        f"([bold]{summary.duplicate_bytes / 1e9:.1f} GB[/] reclaimed, verified by hash on apply)",
    )
    console.print(f"[bold]{summary.undated:,}[/] undated → unsorted/")

    sources = Table(title="metadata source", title_justify="left", show_edge=False)
    sources.add_column("source")
    sources.add_column("files", justify="right")
    for source, count in sorted(summary.by_source.items(), key=lambda item: -item[1]):
        sources.add_row(source, f"{count:,}")
    console.print(sources)

    years = Table(title="by year", title_justify="left", show_edge=False)
    years.add_column("year")
    years.add_column("files", justify="right")
    for year, count in summary.by_year.items():
        years.add_row(str(year), f"{count:,}")
    console.print(years)

    console.print("[bold]Sample of the planned layout:[/]")
    for placement in sorted(plan.placements, key=lambda item: str(item.destination))[:15]:
        console.print(f"  {placement.destination}")
    console.print("\n[dim]Dry run — nothing was changed.[/]")


@app.command(
    help=(
        "Plan the reorganisation of the takeout in TARGET. This is a dry run: it "
        "reports what would move where, which motion-photo videos would be dropped, "
        "and where each file's date/GPS comes from, without changing anything."
    ),
)
def organise(
    target: TargetArgument,
    *,
    jobs: ScanJobsOption = 16,
    verbose: VerboseOption = False,
) -> None:
    configure_logging(verbose=verbose)
    console.rule("[bold]negative-space · organise (dry run)")
    try:
        mount = find_mount_for(target, read_mounts())
        check_ssh(mount.host)
        exiftool = ensure_exiftool(mount.host, str(mount.export / ".negative-space" / "bin"))
    except NasError as error:
        logger.error("%s", error)
        raise typer.Exit(code=1) from error

    logger.info("exiftool ready on %s (%s)", mount.host, exiftool.rsplit("/", 2)[-2])
    logger.info("Scanning %s (reading sidecars over NFS)…", target)
    keepers, drops = scan(target, jobs=jobs)
    plan = build_plan(keepers, drops)
    _render_report(summarize(plan), plan)
