import json
import time
import logging
from dataclasses import dataclass, field
from datetime import date, datetime
from pathlib import Path
from typing import Optional

import requests
from bs4 import BeautifulSoup
from tenacity import retry, stop_after_attempt, wait_exponential

import sys
sys.path.insert(0, str(__import__('pathlib').Path(__file__).parent.parent.parent))
import config

logger = logging.getLogger(__name__)

# Browser-consistent header set. The prior set paired a Chrome User-Agent with a
# Firefox-style Accept-Language ("en-US,en;q=0.5") and omitted the Sec-Fetch-*
# and Upgrade-Insecure-Requests headers a real Chrome sends — a fingerprint
# mismatch that some CDN bot filters (Akamai, in front of federalreserve.gov and
# several regional banks) can flag. This set matches Chrome's real request.
HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/120.0.0.0 Safari/537.36"
    ),
    "Accept": (
        "text/html,application/xhtml+xml,application/xml;q=0.9,"
        "image/avif,image/webp,*/*;q=0.8"
    ),
    "Accept-Language": "en-US,en;q=0.9",
    "Accept-Encoding": "gzip, deflate, br",
    "Upgrade-Insecure-Requests": "1",
    "Sec-Fetch-Dest": "document",
    "Sec-Fetch-Mode": "navigate",
    "Sec-Fetch-Site": "none",
    "Sec-Fetch-User": "?1",
    "Connection": "keep-alive",
}

# ---------------------------------------------------------------------------
# Fetch-failure manifest
#
# Root cause of the July "scraped news instead of the speech" incidents: the
# 5:30am collection runs on GitHub Actions (Azure cloud IP), which the Fed CDN
# intermittently answers with HTTP 403. On a 403, fetch_speech_text() returns ""
# and the calling scraper does `if not text: continue` — so the speech is
# SILENTLY DROPPED, indistinguishable from "no new speeches." The gap was then
# backfilled by hand from media coverage.
#
# Fix: every HTTP request funnels through BaseScraper.get(). When a request
# fails for good (after retries), we record the URL here. cmd_collect writes the
# accumulated list to data/raw/_fetch_failures.json and prints it. The file is
# committed by the Actions workflow, so the local machine (residential IP, which
# is NOT blocked — verified) can see exactly what to recover by simply re-running
# `python3 main.py refetch` (or `collect`); is_already_saved() skips everything
# already captured, so only the missing transcripts are re-fetched.
#
# NEVER substitute media/news coverage for a missing transcript. If refetch from
# a non-blocked IP still fails, mark the speech NOT SCORED / TRANSCRIPT PENDING.
# ---------------------------------------------------------------------------
FETCH_FAILURES_PATH = config.LOCAL_RAW / "_fetch_failures.json"
_FETCH_FAILURES: list[dict] = []


def reset_fetch_failures() -> None:
    """Clear the in-memory failure list at the start of a collection run."""
    _FETCH_FAILURES.clear()


def record_fetch_failure(url: str, source: str = "", status: Optional[int] = None,
                         reason: str = "") -> None:
    """Record a URL that could not be fetched (after retries)."""
    if any(f["url"] == url for f in _FETCH_FAILURES):
        return
    _FETCH_FAILURES.append({
        "url": url,
        "source": source,
        "status": status,
        "reason": reason[:200],
        "seen": datetime.utcnow().isoformat(timespec="seconds") + "Z",
    })
    logger.warning(f"FETCH FAILURE recorded [{status}] {url} ({source})")


def get_fetch_failures() -> list[dict]:
    return list(_FETCH_FAILURES)


def flush_fetch_failures() -> list[dict]:
    """Write this run's failures to the manifest (overwrites), return the list.

    The manifest reflects the LAST run's unrecovered URLs. A subsequent run from
    a non-blocked IP overwrites it with its own (near-empty) result once the
    transcripts are recovered.
    """
    FETCH_FAILURES_PATH.parent.mkdir(parents=True, exist_ok=True)
    if _FETCH_FAILURES:
        FETCH_FAILURES_PATH.write_text(
            json.dumps(_FETCH_FAILURES, indent=2), encoding="utf-8"
        )
    elif FETCH_FAILURES_PATH.exists():
        # A clean run supersedes any stale failure manifest.
        FETCH_FAILURES_PATH.unlink()
    return list(_FETCH_FAILURES)


@dataclass
class SpeechRecord:
    speaker: str
    date: date
    title: str
    url: str
    text: str
    source: str  # e.g. "fed_board", "boston", "new_york"
    doc_type: str = "speech"  # speech, statement, minutes, testimony, pressconf
    event: str = ""
    tier: int = 3
    voter: bool = False
    raw_filename: str = ""
    metadata: dict = field(default_factory=dict)


# Last-name → canonical name mapping built from config at import time
_LAST_NAME_MAP: dict[str, str] = {}

def _build_last_name_map() -> None:
    all_names = set(config.TIER_1_SPEAKERS) | config.TIER_2_VOTERS
    for name in all_names:
        parts = name.split()
        if parts:
            _LAST_NAME_MAP[parts[-1].lower()] = name

_build_last_name_map()


def _canonical_name(raw: str) -> str:
    """Resolve 'Tom Barkin', 'Christopher J. Waller', etc. to the canonical name."""
    raw = raw.strip()
    # Exact match first
    if raw in config.TIER_1_SPEAKERS or raw in config.TIER_2_VOTERS:
        return raw
    # Last-name match (handles middle initials, nicknames like "Tom" vs "Thomas")
    parts = raw.split()
    if parts:
        last = parts[-1].lower().rstrip(".,")
        if last in _LAST_NAME_MAP:
            return _LAST_NAME_MAP[last]
    return raw


def get_tier(speaker: str) -> tuple[int, bool]:
    name = _canonical_name(speaker)
    if name in config.TIER_1_SPEAKERS:
        return 1, True
    if name in config.TIER_2_VOTERS:
        return 2, True
    return 3, False


class BaseScraper:
    source_name: str = "unknown"

    def __init__(self):
        self.session = requests.Session()
        self.session.headers.update(HEADERS)
        self._last_request = 0.0

    @retry(stop=stop_after_attempt(config.MAX_RETRIES), wait=wait_exponential(min=2, max=10))
    def _get_with_retry(self, url: str) -> requests.Response:
        elapsed = time.time() - self._last_request
        if elapsed < config.REQUEST_DELAY_SECONDS:
            time.sleep(config.REQUEST_DELAY_SECONDS - elapsed)
        resp = self.session.get(url, timeout=config.REQUEST_TIMEOUT)
        resp.raise_for_status()
        self._last_request = time.time()
        return resp

    def get(self, url: str) -> requests.Response:
        """Fetch a URL, retrying transient failures. On a FINAL failure (e.g. a
        persistent 403 from a cloud IP), record the URL to the failure manifest
        so the gap is visible and recoverable — then re-raise so callers behave
        as before."""
        try:
            return self._get_with_retry(url)
        except Exception as e:
            # tenacity wraps the real error in a RetryError; unwrap to the
            # underlying HTTPError so we capture the actual status (403 vs 404).
            underlying = e
            last = getattr(e, "last_attempt", None)
            if last is not None:
                try:
                    underlying = last.exception() or e
                except Exception:
                    underlying = e
            status = getattr(getattr(underlying, "response", None), "status_code", None)
            record_fetch_failure(url, source=self.source_name, status=status,
                                 reason=str(underlying))
            raise

    def soup(self, url: str) -> BeautifulSoup:
        resp = self.get(url)
        return BeautifulSoup(resp.text, "lxml")

    def is_after_cutoff(self, d: date) -> bool:
        cutoff = date.fromisoformat(config.SPEECH_START_DATE)
        return d >= cutoff

    def fetch_speeches(self) -> list[SpeechRecord]:
        raise NotImplementedError

    def fetch_speech_text(self, url: str) -> str:
        raise NotImplementedError
