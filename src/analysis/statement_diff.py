"""
Statement diff helpers — pure text comparison, no API calls.
Interpretation is done interactively by Claude Code.
"""
import difflib
from pathlib import Path

import sys
sys.path.insert(0, str(Path(__file__).parent.parent.parent))
import config


def load_latest_statements(n: int = 2) -> list[tuple[str, str]]:
    """Return up to n most recent (filename, text) from local statements dir."""
    stmt_dir = config.LOCAL_RAW / "statements"
    if not stmt_dir.exists():
        return []
    files = sorted(stmt_dir.glob("*.txt"), reverse=True)[:n]
    return [(f.name, f.read_text(encoding="utf-8")) for f in reversed(files)]


def build_diff(prior_text: str, current_text: str) -> str:
    """Produce a unified diff between two statement texts."""
    prior_lines = [l.strip() for l in prior_text.splitlines() if l.strip()]
    curr_lines = [l.strip() for l in current_text.splitlines() if l.strip()]
    diff = list(difflib.unified_diff(prior_lines, curr_lines, lineterm="", n=1))
    return "\n".join(diff)


def prepare_diff_context() -> str:
    """
    Return a formatted string with both statements + their diff,
    ready to paste into a Claude Code session for interpretation.
    """
    statements = load_latest_statements(2)
    if len(statements) < 2:
        return "Not enough statements for diff (need at least 2 saved)."

    (prior_name, prior_text), (curr_name, curr_text) = statements[0], statements[1]
    diff = build_diff(prior_text, curr_text)

    return (
        f"STATEMENT DIFF\n{'='*60}\n"
        f"Prior:   {prior_name}\n"
        f"Current: {curr_name}\n"
        f"{'='*60}\n\n"
        f"PRIOR STATEMENT:\n{prior_text}\n\n"
        f"CURRENT STATEMENT:\n{curr_text}\n\n"
        f"DIFF (- removed, + added):\n{diff}\n"
    )
