"""
CLI entry point for WorkAssistant scanning operations.

Usage examples:
  python -m workassistant.cli scan --location /path/to/projects
  python -m workassistant.cli scan --location /path/to/projects --full
  python -m workassistant.cli scan --resume
  python -m workassistant.cli scan --dry-run
  python -m workassistant.cli scan --workers 2
  python -m workassistant.cli costs --days 30
  python -m workassistant.cli costs --history --group-by week
"""
import argparse
import asyncio
import sys
from pathlib import Path


# ---------------------------------------------------------------------------
# Scan command
# ---------------------------------------------------------------------------

async def cmd_scan(args) -> None:
    from workassistant.database import async_session_maker
    from workassistant.models.project_location import ProjectLocation
    from workassistant.scanning.scanner import ProjectScanner
    from sqlalchemy import select

    location_path = None
    location_id = None

    if args.location:
        location_path = str(Path(args.location).expanduser().resolve())
        if not Path(location_path).exists():
            print(f"Error: location does not exist: {location_path}", file=sys.stderr)
            sys.exit(1)

        async with async_session_maker() as session:
            result = await session.execute(
                select(ProjectLocation).where(ProjectLocation.path == location_path)
            )
            record = result.scalar_one_or_none()
            if not record:
                record = ProjectLocation(
                    path=location_path, is_primary=False, is_active=True
                )
                session.add(record)
                await session.commit()
                await session.refresh(record)
            location_id = record.id

    elif args.resume:
        # Pick the most recent active location
        from workassistant.models.scan_checkpoint import ProjectScanCheckpoint
        async with async_session_maker() as session:
            result = await session.execute(
                select(ProjectScanCheckpoint)
                .where(ProjectScanCheckpoint.is_active == True)
                .order_by(ProjectScanCheckpoint.timestamp.desc())
                .limit(1)
            )
            cp = result.scalar_one_or_none()
            if cp is None:
                print("No active checkpoint found to resume.", file=sys.stderr)
                sys.exit(1)
            location_id = cp.location_id
            print(f"Resuming scan for location_id={location_id} from checkpoint {cp.scan_id}")
    else:
        print("Error: --location or --resume required.", file=sys.stderr)
        sys.exit(1)

    incremental = not args.full

    def progress_cb_sync(progress: dict):
        phase = progress.get("phase", "")
        proj = progress.get("projects_processed", 0)
        proj_total = progress.get("projects_total", "?")
        commits = progress.get("commits_processed", 0)
        pct = progress.get("progress_percent", 0)
        cur = progress.get("current_project") or ""
        print(
            f"\r[{phase:16s}] projects {proj}/{proj_total}  "
            f"commits {commits}  {pct:3d}%  {cur[:40]}",
            end="",
            flush=True,
        )

    async def progress_cb(progress: dict) -> None:
        progress_cb_sync(progress)

    if args.dry_run:
        print("DRY RUN mode — no writes will occur.")

    print(f"\nStarting scan (incremental={incremental}, workers={args.workers}) ...")
    scanner = ProjectScanner(
        location_id=location_id,
        worker_id=0,
        progress_callback=progress_cb,
        dry_run=args.dry_run,
        incremental=incremental,
    )

    try:
        result = await scanner.run()
        print()  # newline after progress line
        print("\n=== Scan Complete ===")
        print(f"  Projects found:       {result['projects_found']}")
        print(f"  Projects processed:   {result['projects_processed']}")
        print(f"  Commits analyzed:     {result['commits_analyzed']}")
        print(f"  Commits skipped (dup):{result['commits_skipped_dup']}")
        print(f"  Commits skipped (old):{result['commits_skipped_old']}")
        print(f"  Files indexed:        {result['files_indexed']}")
        print(f"  Journal entries:      {result['journal_entries_created']}")
        print(f"  AI calls made:        {result['ai_calls']}")
        print(f"  AI cost (USD):       ${result['ai_cost_usd']:.6f}")
        if result["errors"]:
            print(f"\n  Errors ({len(result['errors'])}):")
            for e in result["errors"][:10]:
                print(f"    - {e}")
    except KeyboardInterrupt:
        print("\nScan interrupted.")


# ---------------------------------------------------------------------------
# Cost command
# ---------------------------------------------------------------------------

async def cmd_costs(args) -> None:
    from workassistant.tools.cost_tools import (
        get_scan_cost_summary,
        get_api_cost_history,
        get_project_cost_breakdown,
    )

    if args.history:
        result = await get_api_cost_history(days=args.days, group_by=args.group_by)
        print(f"\n=== API Cost History (last {args.days} days, grouped by {args.group_by}) ===")
        print(f"Total cost: ${result['total_cost_usd']:.6f}")
        for entry in result["history"]:
            print(
                f"  {entry['period']:20s}  calls={entry['calls']:5d}  "
                f"tokens={entry['tokens']:8d}  cost=${entry['cost_usd']:.6f}"
            )
    elif args.projects:
        result = await get_project_cost_breakdown(top_n=args.top)
        print(f"\n=== Cost by Project (top {args.top}) ===")
        print(f"Total cost: ${result['total_cost_usd']:.6f}")
        for p in result["projects"]:
            print(
                f"  {p['project_name']:30s}  commits={p['commits_summarized']:5d}  "
                f"cost=${p['total_cost_usd']:.6f}"
            )
    else:
        result = await get_scan_cost_summary(days=args.days)
        print(f"\n=== Scan Cost Summary (last {args.days} days) ===")
        print(f"  Total API calls: {result['total_calls']}")
        print(f"  Total cost:     ${result['total_cost_usd']:.6f}")
        print(f"  Avg per call:   ${result['avg_cost_per_call']:.6f}")
        print(f"  Input tokens:    {result['total_input_tokens']:,}")
        print(f"  Output tokens:   {result['total_output_tokens']:,}")
        if result["by_model"]:
            print("  By model:")
            for model, stats in result["by_model"].items():
                print(
                    f"    {model:20s}  calls={stats['calls']}  "
                    f"cost=${stats['cost_usd']:.6f}"
                )


# ---------------------------------------------------------------------------
# Argument parsing
# ---------------------------------------------------------------------------

def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="workassistant",
        description="WorkAssistant CLI — project scanning and cost reporting",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    # scan sub-command
    scan_p = sub.add_parser("scan", help="Scan projects in a location")
    scan_p.add_argument("--location", "-l", help="Directory to scan")
    scan_p.add_argument("--resume", "-r", action="store_true", help="Resume from last checkpoint")
    scan_p.add_argument("--full", action="store_true", help="Full re-scan (ignore incremental state)")
    scan_p.add_argument("--dry-run", action="store_true", help="Show what would be scanned without writing")
    scan_p.add_argument("--workers", "-w", type=int, default=4, help="Number of parallel workers")

    # costs sub-command
    costs_p = sub.add_parser("costs", help="View AI API cost reports")
    costs_p.add_argument("--days", type=int, default=30, help="Days of history to show")
    costs_p.add_argument("--history", action="store_true", help="Show time-series cost history")
    costs_p.add_argument("--projects", action="store_true", help="Show cost breakdown by project")
    costs_p.add_argument("--group-by", choices=["day", "week", "model"], default="day")
    costs_p.add_argument("--top", type=int, default=20, help="Top N projects to show")

    return parser


def main() -> None:
    parser = build_parser()
    args = parser.parse_args()

    if args.command == "scan":
        asyncio.run(cmd_scan(args))
    elif args.command == "costs":
        asyncio.run(cmd_costs(args))
    else:
        parser.print_help()


if __name__ == "__main__":
    main()
