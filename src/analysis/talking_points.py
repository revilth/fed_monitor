"""
Talking point extraction helpers — pure file I/O, no API calls.
Cross-official analysis is done interactively by Claude Code.
"""
import re
from pathlib import Path

import sys
sys.path.insert(0, str(Path(__file__).parent.parent.parent))
from src.storage.local_store import load_recent_scored


def extract_key_sentences(scored_text: str) -> tuple[str, str, list[str]]:
    """
    Parse a scored document.
    Returns (speaker, tier, list_of_key_sentences).
    """
    speaker = ""
    tier = "3"
    m = re.search(r"^SPEAKER:\s*(.+)$", scored_text, re.MULTILINE)
    if m:
        speaker = m.group(1).strip()
    m = re.search(r"^TIER:\s*(\d)", scored_text, re.MULTILINE)
    if m:
        tier = m.group(1)

    sentences = []
    in_block = False
    for line in scored_text.splitlines():
        if line.strip().startswith("KEY SENTENCES:"):
            in_block = True
            continue
        if in_block:
            if line.strip() == "" or re.match(r"^[A-Z ]+:", line):
                break
            m = re.match(r'^\d+\.\s+"(.+?)"', line)
            if m:
                sentences.append(m.group(1))

    return speaker, tier, sentences


def build_talking_points_context(days: int = 30) -> str:
    """
    Collect all key sentences from recent scored docs and format them
    for Claude Code to analyze for coordinated messaging.
    """
    recent = load_recent_scored(days)
    if not recent:
        return f"No scored documents found in the past {days} days."

    lines = [f"CROSS-OFFICIAL KEY SENTENCES — past {days} days\n{'='*60}"]
    for filename, text in recent:
        speaker, tier, sents = extract_key_sentences(text)
        if not sents:
            continue
        lines.append(f"\n[{speaker} | Tier {tier}]")
        for s in sents:
            lines.append(f'  • "{s}"')

    return "\n".join(lines)
