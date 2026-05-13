"""
Saves SpeechRecords to the local data/ directory tree that mirrors
the Google Drive folder structure.
"""
import logging
import re
from pathlib import Path

import sys
sys.path.insert(0, str(Path(__file__).parent.parent.parent))
import config
from src.scrapers.base import SpeechRecord

logger = logging.getLogger(__name__)

_DOC_TYPE_DIR = {
    "speech":    config.LOCAL_RAW / "speeches",
    "statement": config.LOCAL_RAW / "statements",
    "minutes":   config.LOCAL_RAW / "minutes",
    "testimony": config.LOCAL_RAW / "testimony",
    "pressconf": config.LOCAL_RAW / "pressconferences",
}


def _sanitize(name: str) -> str:
    return re.sub(r"[^\w\-]", "_", name).strip("_")


def raw_path(rec: SpeechRecord) -> Path:
    base = _DOC_TYPE_DIR.get(rec.doc_type, config.LOCAL_RAW / rec.doc_type)
    year_str = str(rec.date.year)
    speaker_dir = _sanitize(rec.speaker)
    date_str = rec.date.strftime("%Y%m%d")
    title_slug = _sanitize(rec.title)[:60]
    filename = f"{date_str}_{title_slug}.txt"

    if rec.doc_type == "speech":
        return base / year_str / speaker_dir / filename
    else:
        return base / filename


def scored_path(rec: SpeechRecord) -> Path:
    base = config.LOCAL_SCORED / rec.doc_type + "s" if rec.doc_type != "pressconf" else config.LOCAL_SCORED / "pressconfs"
    date_str = rec.date.strftime("%Y%m%d")
    speaker_slug = _sanitize(rec.speaker)
    return config.LOCAL_SCORED / "speeches" / f"{date_str}_{speaker_slug}_scored.txt"


def save_raw(rec: SpeechRecord) -> Path:
    path = raw_path(rec)
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        logger.debug(f"Already exists, skipping: {path.name}")
        return path
    path.write_text(rec.text, encoding="utf-8")
    rec.raw_filename = str(path)
    logger.info(f"Saved raw: {path}")
    return path


def save_scored(rec: SpeechRecord, scored_text: str) -> Path:
    date_str = rec.date.strftime("%Y%m%d")
    speaker_slug = _sanitize(rec.speaker)
    filename = f"{date_str}_{speaker_slug}_scored.txt"
    path = config.LOCAL_SCORED / "speeches" / filename
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(scored_text, encoding="utf-8")
    logger.info(f"Saved scored: {path}")
    return path


def save_report(report_text: str, report_type: str = "weekly") -> Path:
    from datetime import date
    date_str = date.today().strftime("%Y%m%d")
    filename = f"{date_str}_{report_type}_report.txt"
    path = config.LOCAL_REPORTS / report_type / filename
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(report_text, encoding="utf-8")
    logger.info(f"Saved report: {path}")
    return path


def is_already_saved(rec: SpeechRecord) -> bool:
    return raw_path(rec).exists()


def load_recent_scored(days: int = 30) -> list[tuple[str, str]]:
    """Return (filename, content) for scored speeches in the past N days."""
    from datetime import date, timedelta
    cutoff = date.today() - timedelta(days=days)
    results = []
    scored_dir = config.LOCAL_SCORED / "speeches"
    if not scored_dir.exists():
        return results
    for f in sorted(scored_dir.glob("*.txt")):
        try:
            date_str = f.stem[:8]
            doc_date = date(int(date_str[:4]), int(date_str[4:6]), int(date_str[6:8]))
            if doc_date >= cutoff:
                results.append((f.name, f.read_text(encoding="utf-8")))
        except Exception:
            continue
    return results
