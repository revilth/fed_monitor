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
# Root cause of the July "scraped news instead of the speech" incidents: a
# fetch that fails returns "" and the calling scraper does `if not text:
# continue` — so the document is SILENTLY DROPPED, indistinguishable from "no
# new speeches." The gap was then backfilled by hand from media coverage.
#
# Fix: every HTTP request funnels through BaseScraper.get(). When a request
# fails for good (after retries), we record the URL here. cmd_collect writes the
# accumulated list to data/raw/_fetch_failures.json and prints it. The file is
# committed by the Actions workflow so the gap is visible and recoverable via
# `python3 main.py refetch`; is_already_saved() skips everything already
# captured, so only the missing transcripts are re-fetched.
#
# ON ATTRIBUTION (corrected 2026-08-03): this module used to assert that
# failures were "HTTP 403 from the Fed CDN blocking the GitHub Actions cloud
# IP." That was wrong and it propagated into reports and stub files. Verified
# from the Actions logs: the scheduled collect job reaches federalreserve.gov
# and every regional bank fine. The failures recorded on 2026-08-01/02/03 came
# from a DIFFERENT environment — an agent sandbox behind an egress proxy that
# refuses CONNECT with a tunnel-level 403, so `status` is null and the Fed never
# answered at all. Those are completely different faults with different fixes,
# so classify_failure() now labels the kind rather than assuming a cause. Do not
# reintroduce a hardcoded "Fed CDN blocked us" message anywhere.
#
# NEVER substitute media/news coverage for a missing transcript. If refetch from
# a non-blocked network still fails, mark the document NOT SCORED / TRANSCRIPT
# PENDING.
# ---------------------------------------------------------------------------
FETCH_FAILURES_PATH = config.LOCAL_RAW / "_fetch_failures.json"
_FETCH_FAILURES: list[dict] = []
_FETCH_SUCCESSES: set[str] = set()


def reset_fetch_failures() -> None:
    """Clear the in-memory failure/success lists at the start of a run."""
    _FETCH_FAILURES.clear()
    _FETCH_SUCCESSES.clear()


def classify_failure(status: Optional[int], reason: str) -> str:
    """Name the fault so it is not misdiagnosed later.

    Distinguishing these matters: a proxy tunnel refusal is a local egress
    problem, an origin 403 is a bot filter, and a 404 is a dead link. They were
    all previously reported as "cloud-IP 403 from the Fed CDN".
    """
    r = (reason or "").lower()
    if "proxyerror" in r or "tunnel connection failed" in r or "unable to connect to proxy" in r:
        return "proxy_blocked"          # local egress proxy refused CONNECT
    if status == 403:
        return "origin_403"             # the site itself refused us
    if status == 404:
        return "not_found"
    if status is not None and 500 <= status < 600:
        return "origin_5xx"
    if "timeout" in r or "timed out" in r:
        return "timeout"
    if "connection" in r or "resolve" in r or "dns" in r:
        return "connection"
    if status is not None:
        return f"http_{status}"
    return "unknown"


def record_fetch_success(url: str) -> None:
    """Note a URL fetched successfully, so a stale manifest entry can clear."""
    _FETCH_SUCCESSES.add(url)


def record_fetch_failure(url: str, source: str = "", status: Optional[int] = None,
                         reason: str = "") -> None:
    """Record a URL that could not be fetched (after retries)."""
    if any(f["url"] == url for f in _FETCH_FAILURES):
        return
    kind = classify_failure(status, reason)
    now = datetime.utcnow().isoformat(timespec="seconds") + "Z"
    _FETCH_FAILURES.append({
        "url": url,
        "source": source,
        "kind": kind,
        "status": status,
        "reason": (reason or "")[:200],
        "first_seen": now,
        "last_seen": now,
    })
    logger.warning(f"FETCH FAILURE recorded [{kind} status={status}] {url} ({source})")


def get_fetch_failures() -> list[dict]:
    return list(_FETCH_FAILURES)


def _load_manifest() -> list[dict]:
    if not FETCH_FAILURES_PATH.exists():
        return []
    try:
        data = json.loads(FETCH_FAILURES_PATH.read_text(encoding="utf-8"))
        return data if isinstance(data, list) else []
    except (json.JSONDecodeError, OSError):
        return []


def flush_fetch_failures() -> list[dict]:
    """Merge this run's failures into the manifest and write it.

    PREVIOUS BEHAVIOUR WAS A BUG: any run with no failures of its own deleted
    the manifest outright ("a clean run supersedes a stale manifest"). But a run
    that never *attempted* a URL is not evidence that URL was recovered. On
    2026-08-03 the scheduled collect job did exactly this — it wiped the list of
    three unrecovered July 31 dissent statements before anything had fetched
    them, destroying the only machine-readable record of the gap.

    An entry is now cleared ONLY when this run actually fetched that URL
    successfully. Everything else carries forward, keeping first_seen so a
    long-unrecovered gap is visible as such.
    """
    FETCH_FAILURES_PATH.parent.mkdir(parents=True, exist_ok=True)

    new_by_url = {f["url"]: f for f in _FETCH_FAILURES}
    merged: list[dict] = []

    # Carry forward prior entries unless this run actually recovered them.
    for old in _load_manifest():
        url = old.get("url")
        if not url or url in _FETCH_SUCCESSES:
            continue                      # genuinely recovered — drop it
        if url in new_by_url:
            fresh = dict(new_by_url.pop(url))
            fresh["first_seen"] = old.get("first_seen") or old.get("seen") or fresh["first_seen"]
            merged.append(fresh)
        else:
            merged.append(old)            # not retried this run — keep pending

    merged.extend(new_by_url.values())

    if merged:
        FETCH_FAILURES_PATH.write_text(
            json.dumps(merged, indent=2), encoding="utf-8"
        )
    elif FETCH_FAILURES_PATH.exists():
        FETCH_FAILURES_PATH.unlink()      # every pending URL recovered
    return merged


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
            resp = self._get_with_retry(url)
            record_fetch_success(url)
            return resp
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
