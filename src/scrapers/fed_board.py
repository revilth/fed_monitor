"""
Federal Reserve Board scraper.

Speech listing URL: /newsevents/2026-speeches.htm
Structure: div.row.eventlist > div.row (one per speech)
  - date:    div.eventlist__time > time
  - title:   div.eventlist__event > p > a (first non-watchLive link)
  - speaker: div.eventlist__event > p.news__speaker
  - venue:   div.eventlist__event > p (last plain <p>)
"""
import logging
import re
from datetime import date, datetime
from urllib.parse import urljoin

import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent.parent))
import config
from src.scrapers.base import BaseScraper, SpeechRecord, get_tier

logger = logging.getLogger(__name__)
BASE_URL = "https://www.federalreserve.gov"
YEAR = date.today().year


class FedBoardScraper(BaseScraper):
    source_name = "fed_board"

    # ------------------------------------------------------------------ #
    # Speeches
    # ------------------------------------------------------------------ #

    def fetch_speeches(self) -> list[SpeechRecord]:
        records = []
        url = f"{BASE_URL}/newsevents/{YEAR}-speeches.htm"
        try:
            soup = self.soup(url)
        except Exception as e:
            logger.error(f"Fed Board speeches page failed: {e}")
            return records

        container = soup.select_one("div.row.eventlist")
        if not container:
            logger.warning("Fed Board: div.row.eventlist not found on page")
            return records

        rows = container.select("div.row")
        logger.info(f"Fed Board: {len(rows)} speech rows found")

        for row in rows:
            rec = self._parse_row(row)
            if rec is None:
                continue
            if not self.is_after_cutoff(rec.date):
                continue
            records.append(rec)

        return records

    def _parse_row(self, row) -> SpeechRecord | None:
        try:
            # Date
            time_el = row.select_one("div.eventlist__time time")
            if not time_el:
                return None
            speech_date = self._parse_date(time_el.get_text(strip=True))
            if speech_date is None:
                return None

            event_div = row.select_one("div.eventlist__event")
            if not event_div:
                return None

            # Title link — skip watchLive anchors
            link_el = None
            for a in event_div.find_all("a", href=True):
                if "watchLive" not in a.get("class", []) and a["href"].startswith("/newsevents/speech/"):
                    link_el = a
                    break
            if not link_el:
                return None

            title = link_el.get_text(strip=True)
            href = urljoin(BASE_URL, link_el["href"])

            # Speaker
            speaker_el = event_div.select_one("p.news__speaker")
            raw_speaker = speaker_el.get_text(strip=True) if speaker_el else ""
            speaker = self._clean_speaker(raw_speaker)

            tier, voter = get_tier(speaker)
            text = self.fetch_speech_text(href)
            if not text:
                return None

            return SpeechRecord(
                speaker=speaker,
                date=speech_date,
                title=title,
                url=href,
                text=text,
                source=self.source_name,
                doc_type="speech",
                tier=tier,
                voter=voter,
            )
        except Exception as e:
            logger.debug(f"Fed Board row parse error: {e}")
            return None

    def fetch_speech_text(self, url: str) -> str:
        try:
            soup = self.soup(url)
            for tag in soup.select("nav, header, footer, script, style, .breadcrumb, .share"):
                tag.decompose()
            content = (
                soup.select_one("div#article")
                or soup.select_one("div.col-md-8")
                or soup.select_one("div#maincontent")
                or soup.find("main")
            )
            return content.get_text(separator="\n", strip=True) if content else ""
        except Exception as e:
            logger.warning(f"Fed Board speech text fetch failed ({url}): {e}")
            return ""

    # ------------------------------------------------------------------ #
    # FOMC Statements, Minutes, Press Conferences
    # ------------------------------------------------------------------ #

    def fetch_fomc_docs(self) -> list[SpeechRecord]:
        records = []
        try:
            soup = self.soup(config.FED_BOARD_FOMC_URL)
        except Exception as e:
            logger.error(f"FOMC calendar page failed: {e}")
            return records

        for block in soup.select("div.fomc-meeting, div.panel"):
            meeting_date = self._extract_meeting_date(block)
            if meeting_date and not self.is_after_cutoff(meeting_date):
                continue
            for link in block.select("a[href]"):
                label = link.get_text(strip=True).lower()
                href = link["href"]
                if not href.startswith("http"):
                    href = urljoin(BASE_URL, href)
                if "statement" in label:
                    doc_type = "statement"
                elif "minutes" in label:
                    doc_type = "minutes"
                elif "press conference" in label or "transcript" in label:
                    doc_type = "pressconf"
                else:
                    continue
                text = self.fetch_speech_text(href)
                if not text:
                    continue
                records.append(SpeechRecord(
                    speaker="FOMC" if doc_type != "pressconf" else "Jerome Powell",
                    date=meeting_date or date.today(),
                    title=f"FOMC {doc_type.title()} {(meeting_date or date.today()).strftime('%Y%m%d')}",
                    url=href, text=text, source=self.source_name,
                    doc_type=doc_type, tier=1, voter=True,
                ))
        return records

    def fetch_testimony(self) -> list[SpeechRecord]:
        records = []
        try:
            soup = self.soup(config.FED_BOARD_TESTIMONY_URL)
        except Exception as e:
            logger.error(f"Testimony page failed: {e}")
            return records

        container = soup.select_one("div.row.eventlist")
        if not container:
            return records

        for row in container.select("div.row"):
            rec = self._parse_row(row)
            if rec:
                rec.doc_type = "testimony"
                records.append(rec)
        return records

    # ------------------------------------------------------------------ #
    # Helpers
    # ------------------------------------------------------------------ #

    def _parse_date(self, text: str) -> date | None:
        text = text.strip()
        for fmt in ("%m/%d/%Y", "%B %d, %Y", "%b %d, %Y", "%Y-%m-%d"):
            try:
                return datetime.strptime(text, fmt).date()
            except ValueError:
                continue
        m = re.search(r"(\d{1,2}/\d{1,2}/\d{4})", text)
        if m:
            try:
                return datetime.strptime(m.group(1), "%m/%d/%Y").date()
            except ValueError:
                pass
        return None

    def _clean_speaker(self, raw: str) -> str:
        # Strip full title prefix — e.g. "Vice Chair for Supervision Michelle W. Bowman"
        # handles multi-word titles like "Vice Chair for Supervision", "Governor", etc.
        raw = re.sub(
            r"^(Chair(?:man)?|Vice\s+Chair(?:\s+for\s+\w+)?|Governor|President"
            r"|Dr\.|Mr\.|Ms\.|Vice\s+Chairman)\s+",
            "", raw, flags=re.I,
        )
        # If "for Supervision" or similar still prepended, strip it
        raw = re.sub(r"^for\s+\w+\s+", "", raw, flags=re.I)
        raw = re.sub(r"\s+(speaks?|remarks?|testimony|testif).*$", "", raw, flags=re.I)
        return raw.strip()

    def _extract_meeting_date(self, block) -> date | None:
        text = block.get_text(" ", strip=True)
        m = re.search(
            r"(January|February|March|April|May|June|July|August|"
            r"September|October|November|December)\s+\d{1,2}(?:[–\-]\d{1,2})?,\s+\d{4}",
            text,
        )
        if m:
            raw = re.sub(r"[–\-]\d{1,2}", "", m.group(0))
            return self._parse_date(raw)
        return None
