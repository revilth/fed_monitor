"""
Weekly report helpers — assembles context from scored files.
The actual report narrative is written by Claude Code.
"""
from datetime import date, timedelta
from pathlib import Path
import re

import sys
sys.path.insert(0, str(Path(__file__).parent.parent.parent))
import config
from src.storage.local_store import load_recent_scored, save_report
from src.analysis.talking_points import build_talking_points_context


def build_weekly_context() -> str:
    """
    Assemble all scored documents from the past 7 days plus talking points
    context into a single block for Claude Code to turn into a report.
    """
    scored_this_week = load_recent_scored(days=7)

    lines = [
        f"WEEKLY FED MONITOR — CONTEXT DUMP",
        f"Week ending: {date.today().isoformat()}",
        f"Cycle regime: {config.CYCLE_REGIME}",
        f"Documents this week: {len(scored_this_week)}",
        "=" * 60,
    ]

    for filename, text in scored_this_week:
        lines.append(f"\n--- {filename} ---")
        lines.append(text[:1500])  # truncate very long scored docs

    lines.append("\n" + "=" * 60)
    lines.append(build_talking_points_context(days=30))

    return "\n".join(lines)
