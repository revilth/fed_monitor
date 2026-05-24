"""
Scoring helpers — pure file I/O, no API calls.
Actual hawk-dove analysis is done interactively by Claude Code.
"""
import re
from pathlib import Path

import sys
sys.path.insert(0, str(Path(__file__).parent.parent.parent))
import config
from src.scrapers.base import SpeechRecord


def scoring_template(rec: SpeechRecord) -> str:
    """Return a blank scoring template pre-filled with document metadata."""
    tier_descs = {1: "Core (Chair/VP/NY Fed)", 2: "FOMC Voter", 3: "FOMC Non-Voter"}
    return f"""DATE: {rec.date.isoformat()}
SPEAKER: {rec.speaker}
TIER: {rec.tier}
TYPE: [A/B/C/D/E/F/G — classify from content]
VOTER STATUS: {"voter" if rec.voter else "non-voter"}
EVENT: [event name if discernible, else "not specified"]
CYCLE CONTEXT: {config.CYCLE_REGIME}

SPEECH STRUCTURE:
- Sections identified: [Labor | Growth | Inflation | Policy implications | Special topic]
- Outlook section present: [yes / no / embedded]

KEY SENTENCES:
1. "[sentence]" — [hawkish / dovish / neutral] — [interpretation]
2.
3.
4.
5.

SHIFT FROM PRIOR SPEECH:
- [directional change, or "no meaningful shift"]

TALKING POINTS FLAGGED: [yes / no]
-

MEDIA PICKUP: not yet checked

ANALYST REVIEW NEEDED: [yes / no]
-
"""


def find_prior_scored(speaker: str) -> tuple[Path | None, str]:
    """Return (path, text) of the most recent scored file for this speaker."""
    scored_dir = config.LOCAL_SCORED / "speeches"
    if not scored_dir.exists():
        return None, ""
    speaker_slug = re.sub(r"[^\w]", "_", speaker)
    matches = sorted(scored_dir.glob(f"*_{speaker_slug}_scored.txt"), reverse=True)
    if not matches:
        # Try partial match on speaker last name
        last = speaker.split()[-1] if speaker.split() else ""
        matches = sorted(scored_dir.glob(f"*{last}*scored.txt"), reverse=True)
    if matches:
        return matches[0], matches[0].read_text(encoding="utf-8")
    return None, ""
