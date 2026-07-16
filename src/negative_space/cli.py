"""Command-line entry point for organising a Google Photos takeout.

The takeout typically lives on a NAS, so the CLI is deliberately verbose: it
narrates each step and prefers directory reads that don't fan out into a stat
per entry, keeping chatter across the network to a minimum.
"""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING, Annotated

import typer
from rich.progress import BarColumn, MofNCompleteColumn, Progress, TextColumn, TimeElapsedColumn
from rich.table import Table

from negative_space.apply import ApplyTarget, run_apply
from negative_space.console import configure_logging, console, logger
from negative_space.extract import ExtractOptions
from negative_space.extract import run as run_extraction
from negative_space.nas import NasError, check_ssh, find_mount_for, read_mounts, resolve_remote
from negative_space.plan import build_plan, scan, summarize
from negative_space.remote import ensure_exiftool

if TYPE_CHECKING:
    from negative_space.apply import ApplyOutcome
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


def _render_apply_result(outcome: ApplyOutcome) -> None:
    counts = outcome.counts

    def total(suffix: str) -> int:
        return sum(value for key, value in counts.items() if key.endswith(suffix))

    console.print(f"\n[bold green]Applied {total(':ok'):,} operations[/] on the NAS.")
    if total(":skip"):
        console.print(f"[dim]{total(':skip'):,} already done — skipped on this resumed run.[/]")
    differs = counts.get("duplicate:differs", 0)
    if differs:
        console.print(f"[yellow]{differs:,} duplicate(s) were not byte-identical and were kept.[/]")
    if total(":error"):
        console.print(
            f"[red]{total(':error'):,} operation(s) failed[/] — see the executor output above."
        )

    table = Table(title="apply results", title_justify="left", show_edge=False)
    table.add_column("operation")
    table.add_column("count", justify="right")
    for key, count in sorted(counts.items()):
        table.add_row(key, f"{count:,}")
    console.print(table)


ApplyOption = Annotated[
    bool,
    typer.Option("--apply", help="Carry out the reorganisation on the NAS (default: dry run)."),
]

YesOption = Annotated[
    bool,
    typer.Option("--yes", "-y", help="Skip the confirmation prompt before applying."),
]

LogOption = Annotated[
    Path,
    typer.Option(
        "--log",
        help="Where to write the apply progress log (for diagnosing a failed run).",
        show_default=False,
        dir_okay=False,
        writable=True,
    ),
]


def _run_apply_with_progress(
    plan: LibraryPlan, target: ApplyTarget, log_path: Path
) -> ApplyOutcome:
    columns = (
        TextColumn("[cyan]Applying[/]"),
        BarColumn(),
        MofNCompleteColumn(),
        TimeElapsedColumn(),
    )
    with Progress(*columns, console=console) as progress:
        task = progress.add_task("apply", total=None)

        def advance(done: int, total: int) -> None:
            progress.update(task, completed=done, total=total)

        return run_apply(plan, target, log_path=log_path, on_progress=advance)


@app.command(
    help=(
        "Plan the reorganisation of the takeout in TARGET. By default this is a dry "
        "run: it reports what would move where, which motion-photo videos and "
        "duplicates would be dropped, and where each file's date/GPS comes from, "
        "without changing anything. Pass --apply to carry it out on the NAS."
    ),
)
def organise(  # noqa: PLR0913 - each parameter is a distinct user-facing CLI option
    target: TargetArgument,
    *,
    jobs: ScanJobsOption = 16,
    apply_changes: ApplyOption = False,
    yes: YesOption = False,
    log: LogOption = Path("organise-apply.log"),
    verbose: VerboseOption = False,
) -> None:
    configure_logging(verbose=verbose)
    console.rule(f"[bold]negative-space · organise ({'apply' if apply_changes else 'dry run'})")
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

    if not apply_changes:
        console.print(
            "\n[dim]Dry run — nothing was changed. Re-run with --apply to carry it out.[/]"
        )
        return

    target_config = ApplyTarget(
        mount=mount,
        exiftool=exiftool,
        output_root=f"{resolve_remote(target, mount).path}-organised",
        work_dir=str(mount.export / ".negative-space" / "apply"),
    )
    console.print(
        f"\n[bold red]This rewrites, moves and deletes files on {mount.host}[/] — "
        f"organising into [bold]{target_config.output_root}[/]. This cannot be undone."
    )
    if not yes:
        typer.confirm("Proceed?", abort=True)

    log_path = log.resolve()
    console.print(f"[dim]Progress is logged to {log_path}[/]")
    try:
        outcome = _run_apply_with_progress(plan, target_config, log_path)
    except NasError as error:
        logger.error("%s", error)
        console.print(f"[yellow]Share the log at {log_path} to diagnose the failure.[/]")
        raise typer.Exit(code=1) from error
    _render_apply_result(outcome)
    console.print(f"[dim]Full log: {log_path}[/]")
