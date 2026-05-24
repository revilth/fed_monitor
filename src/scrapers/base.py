import time
import logging
from dataclasses import dataclass, field
from datetime import date, datetime
from typing import Optional

import requests
from bs4 import BeautifulSoup
from tenacity import retry, stop_after_attempt, wait_exponential

import sys
sys.path.insert(0, str(__import__('pathlib').Path(__file__).parent.parent.parent))
import config

logger = logging.getLogger(__name__)

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/120.0.0.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.5",
}


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
    def get(self, url: str) -> requests.Response:
        elapsed = time.time() - self._last_request
        if elapsed < config.REQUEST_DELAY_SECONDS:
            time.sleep(config.REQUEST_DELAY_SECONDS - elapsed)
        resp = self.session.get(url, timeout=config.REQUEST_TIMEOUT)
        resp.raise_for_status()
        self._last_request = time.time()
        return resp

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
