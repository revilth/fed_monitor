#!/usr/bin/env python3
"""
Fed Communication Monitor — Main entrypoint.

Data collection (run these from the terminal):
    python main.py collect          # Scrape Fed Board + all regional sites
    python main.py youtube          # Scrape YouTube channels for transcripts
    python main.py youtube <url>    # Fetch transcript for a single video URL

Analysis (run these, then paste output into Claude Code for scoring):
    python main.py pending          # List + print all unscored raw files
    python main.py diff             # Print statement diff for Claude Code to interpret
    python main.py talking-points   # Print key sentences for Claude Code to cluster
    python main.py weekly           # Print weekly context for Claude Code to report on

Scheduling:
    python main.py schedule         # Start daily collection scheduler
"""
import argparse
import logging
import sys
from pathlib import Path

from rich.console import Console
from rich.logging import RichHandler

import config

logging.basicConfig(
    level=logging.INFO,
    format="%(message)s",
    handlers=[RichHandler(rich_tracebacks=True)],
)
logger = logging.getLogger(__name__)
console = Console()


# ---------------------------------------------------------------------------
# Collection commands
# ---------------------------------------------------------------------------

def cmd_collect():
    from src.scrapers.fed_board import FedBoardScraper
    from src.scrapers.regional_feds import ALL_REGIONAL_SCRAPERS
    from src.storage.local_store import save_raw, is_already_saved

    all_records = []

    console.print("[bold]Scraping Fed Board...[/bold]")
    board = FedBoardScraper()

    speeches = board.fetch_speeches()
    console.print(f"  Speeches: {len(speeches)}")
    all_records.extend(speeches)

    fomc_docs = board.fetch_fomc_docs()
    console.print(f"  FOMC docs (statements/minutes/pressconf): {len(fomc_docs)}")
    all_records.extend(fomc_docs)

    testimony = board.fetch_testimony()
    console.print(f"  Testimony: {len(testimony)}")
    all_records.extend(testimony)

    console.print("\n[bold]Scraping regional Fed banks...[/bold]")
    for ScraperClass in ALL_REGIONAL_SCRAPERS:
        scraper = ScraperClass()
        try:
            recs = scraper.fetch_speeches()
            console.print(f"  {scraper.source_name}: {len(recs)}")
            all_records.extend(recs)
        except Exception as e:
            console.print(f"  [red]{scraper.source_name}: ERROR — {e}[/red]")

    console.print(f"\n[bold]Saving {len(all_records)} records...[/bold]")
    new_count = 0
    for rec in all_records:
        if is_already_saved(rec):
            continue
        save_raw(rec)
        new_count += 1
        console.print(f"  [green]✓[/green] {rec.date} {rec.speaker} — {rec.title[:55]}")

    console.print(f"\n[bold green]Done.[/bold green] {new_count} new raw files saved to data/raw/")
    if new_count:
        console.print("Run [bold]python main.py pending[/bold] and paste the output into Claude Code to score.")


def cmd_youtube(video_url: str = ""):
    from src.scrapers.youtube import YouTubeScraper
    from src.storage.local_store import save_raw, is_already_saved

    scraper = YouTubeScraper()

    if video_url:
        console.print(f"[bold]Fetching single video:[/bold] {video_url}")
        rec = scraper.fetch_single_video(video_url)
        records = [rec] if rec else []
    else:
        console.print("[bold]Scanning YouTube channels for FOMC speeches...[/bold]")
        records = scraper.fetch_speeches()

    console.print(f"Found {len(records)} relevant transcripts")
    new_count = 0
    for rec in records:
        if is_already_saved(rec):
            console.print(f"  Already saved: {rec.speaker} {rec.date}")
            continue
        save_raw(rec)
        auto_label = "(auto-transcript)" if rec.metadata.get("auto_transcript") else "(manual)"
        console.print(f"  [green]✓[/green] {rec.date} {rec.speaker} {auto_label} — {rec.title[:55]}")
        new_count += 1

    console.print(f"\n[bold green]Done.[/bold green] {new_count} new transcripts saved to data/raw/")
    if new_count:
        console.print("Run [bold]python main.py pending[/bold] and paste the output into Claude Code to score.")


# ---------------------------------------------------------------------------
# Analysis context commands (output is pasted into Claude Code)
# ---------------------------------------------------------------------------

def cmd_pending():
    """
    Print all unscored raw speech files to stdout.
    Paste this output into a Claude Code session to score.
    """
    from src.storage.local_store import raw_path, is_already_saved
    from src.scrapers.base import SpeechRecord
    from src.analysis.scorer import scoring_template, find_prior_scored
    import re
    from datetime import date

    raw_speeches = config.LOCAL_RAW / "speeches"
    if not raw_speeches.exists():
        console.print("No raw speeches found. Run [bold]python main.py collect[/bold] first.")
        return

    scored_dir = config.LOCAL_SCORED / "speeches"
    scored_stems = {f.stem for f in scored_dir.glob("*.txt")} if scored_dir.exists() else set()

    pending = []
    for txt_file in sorted(raw_speeches.rglob("*.txt")):
        date_str = txt_file.stem[:8]
        speaker_dir = txt_file.parent.name
        expected_stem = f"{date_str}_{speaker_dir}_scored"
        if expected_stem not in scored_stems:
            pending.append(txt_file)

    if not pending:
        console.print("[green]No pending files — everything is scored.[/green]")
        return

    console.print(f"[bold]{len(pending)} unscored file(s):[/bold]\n")

    for txt_file in pending:
        date_str = txt_file.stem[:8]
        speaker_dir = txt_file.parent.name
        text = txt_file.read_text(encoding="utf-8")

        try:
            doc_date = date(int(date_str[:4]), int(date_str[4:6]), int(date_str[6:8]))
        except Exception:
            doc_date = date.today()

        speaker = speaker_dir.replace("_", " ")
        _, prior_text = find_prior_scored(speaker)

        print(f"\n{'#'*70}")
        print(f"# FILE: {txt_file.name}")
        print(f"# PATH: {txt_file}")
        print(f"# SPEAKER: {speaker}")
        print(f"# DATE: {doc_date.isoformat()}")
        print(f"{'#'*70}\n")
        print("--- SPEECH TEXT ---")
        print(text[:8000])
        if len(text) > 8000:
            print(f"\n[... {len(text)-8000} more chars truncated ...]")
        if prior_text:
            print("\n--- PRIOR SCORED SPEECH (same speaker) ---")
            print(prior_text[:1500])
        print(f"\n--- BLANK SCORING TEMPLATE ---")

        rec = SpeechRecord(
            speaker=speaker,
            date=doc_date,
            title=txt_file.stem[9:],
            url="",
            text=text,
            source="local",
        )
        print(scoring_template(rec))
        print(f"\n# SCORED OUTPUT PATH: {scored_dir / (date_str + '_' + speaker_dir + '_scored.txt')}")


def cmd_diff():
    from src.analysis.statement_diff import prepare_diff_context
    context = prepare_diff_context()
    print(context)
    console.print("\n[dim]Paste the above into Claude Code and ask it to interpret each change.[/dim]")


def cmd_talking_points():
    from src.analysis.talking_points import build_talking_points_context
    context = build_talking_points_context(days=30)
    print(context)
    console.print("\n[dim]Paste the above into Claude Code and ask it to identify coordinated messaging.[/dim]")


def cmd_weekly():
    from src.reports.weekly import build_weekly_context
    context = build_weekly_context()
    print(context)
    console.print("\n[dim]Paste the above into Claude Code and ask it to write the weekly report.[/dim]")


# ---------------------------------------------------------------------------
# Scheduler
# ---------------------------------------------------------------------------

def cmd_schedule():
    import schedule
    import time

    console.print("[bold green]Starting Fed Monitor scheduler...[/bold green]")
    console.print("  Daily 8:00am: collect from all web sources")
    console.print("  Daily 8:30am: scan YouTube channels")

    schedule.every().day.at("08:00").do(cmd_collect)
    schedule.every().day.at("08:30").do(cmd_youtube)

    while True:
        schedule.run_pending()
        time.sleep(60)


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(description="Fed Communication Monitor")
    parser.add_argument(
        "command",
        choices=["collect", "youtube", "pending", "diff", "talking-points", "weekly", "schedule"],
        help="Command to run",
    )
    parser.add_argument(
        "url",
        nargs="?",
        default="",
        help="Optional YouTube video URL (only used with 'youtube' command)",
    )
    args = parser.parse_args()

    commands = {
        "collect": cmd_collect,
        "youtube": lambda: cmd_youtube(args.url),
        "pending": cmd_pending,
        "diff": cmd_diff,
        "talking-points": cmd_talking_points,
        "weekly": cmd_weekly,
        "schedule": cmd_schedule,
    }
    commands[args.command]()


if __name__ == "__main__":
    main()
