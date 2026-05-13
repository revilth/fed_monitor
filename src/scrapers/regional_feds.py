"""
Regional Federal Reserve Bank scrapers — one class per bank.

Verified HTML structures (tested 2026-04-27):

  Boston       div.row > h1.card-title + ul.list-inline.speaker + p.date-and-location
  New York     tr > td.dirColL div (date) | td.dirColR a.paraHeader (title)
  Philadelphia DYNAMIC — JS-rendered, API blocked; speeches collected via Fed Board
  Cleveland    DYNAMIC — JS-rendered listing; individual pages work (/collections/speeches/2026/...)
  Richmond     div.data__row > span.data__date | div.data__title a | div.data__authors p a
  Atlanta      Embedded JSON in <script>: var feed_* = [{Title, Date, Authors, Url}]
  Chicago      No listing page (all return 404); individual speeches at /publications/speeches/YYYY/slug
  St. Louis    DYNAMIC — JS-rendered; no static listing found
  Minneapolis  Person page /people/neel-kashkari — speech links in static HTML
  Kansas City  div.card > time[datetime] | div.body a | div.body p (speaker)
  Dallas       /news/speeches/speeches-leaders — year sections with staff speech links
  San Francisco /news-and-media/speeches/mary-c-daly — li.wp-block-post items
"""
import json
import logging
import re
from datetime import date, datetime
from urllib.parse import urljoin

from bs4 import BeautifulSoup

import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent.parent))
import config
from src.scrapers.base import BaseScraper, SpeechRecord, get_tier

logger = logging.getLogger(__name__)


_MONTH_MAP = {
    "january": 1, "february": 2, "march": 3, "april": 4,
    "may": 5, "june": 6, "july": 7, "august": 8,
    "september": 9, "october": 10, "november": 11, "december": 12,
    "jan": 1, "feb": 2, "mar": 3, "apr": 4,
    "jun": 6, "jul": 7, "aug": 8, "sep": 9, "oct": 10, "nov": 11, "dec": 12,
}


def _clean_text(soup: BeautifulSoup) -> str:
    for tag in soup.select("nav, header, footer, script, style, .breadcrumb, .share, aside"):
        tag.decompose()
    content = (
        soup.select_one("div#article, div.col-md-8, div#maincontent, main, article, div.content")
        or soup.find("body")
    )
    return content.get_text(separator="\n", strip=True) if content else ""


def _fetch_pdf_text(url: str, session: "requests.Session") -> str:
    """Download a PDF and extract its text using the Read tool approach via pdfminer."""
    import tempfile, subprocess, sys
    try:
        resp = session.get(url, timeout=30)
        resp.raise_for_status()
        with tempfile.NamedTemporaryFile(suffix=".pdf", delete=False) as f:
            f.write(resp.content)
            tmp_path = f.name
        # Use pdfminer.six if available, else fall back to pdftotext
        try:
            from pdfminer.high_level import extract_text
            text = extract_text(tmp_path)
        except ImportError:
            result = subprocess.run(
                ["pdftotext", tmp_path, "-"],
                capture_output=True, text=True, timeout=30
            )
            text = result.stdout
        import os; os.unlink(tmp_path)
        return text.strip()
    except Exception as e:
        logger.warning(f"PDF text extraction failed ({url}): {e}")
        return ""


def _parse_date_str(text: str) -> date | None:
    text = re.sub(r"\s*\|.*$", "", text.strip())  # strip "| Location" suffix
    for fmt in (
        "%B %d, %Y", "%b %d, %Y", "%b. %d, %Y",
        "%B %Y", "%m/%d/%Y", "%Y-%m-%d",
        "%d %B %Y", "%Y-%m-%dT%H:%M:%S",
    ):
        try:
            return datetime.strptime(text.strip(), fmt).date()
        except ValueError:
            continue
    m = re.search(r"(\w+\.?\s+\d{1,2},?\s+\d{4})", text)
    if m:
        for fmt in ("%B %d %Y", "%b %d %Y", "%b. %d %Y"):
            try:
                return datetime.strptime(m.group(1).replace(",", "").replace(".", ""), fmt).date()
            except ValueError:
                continue
    m = re.search(r"(\d{4}-\d{2}-\d{2})", text)
    if m:
        try:
            return date.fromisoformat(m.group(1))
        except ValueError:
            pass
    return None


# ---------------------------------------------------------------------------
# Boston Fed
# ---------------------------------------------------------------------------
class BostonFedScraper(BaseScraper):
    """
    Structure: each speech is a div.row containing:
      h1.card-title > a[href*="/speeches/YYYY/"] — title + link
      ul.list-inline.speaker li a                — speaker name
      p.date-and-location                        — "March 6, 2026 | Springfield, MA"
    Full text is in a PDF linked from the speech page as "Full-text Speech (pdf)".
    """
    source_name = "boston"
    base_url = "https://www.bostonfed.org"
    speaker_name = "Susan Collins"

    def fetch_speeches(self) -> list[SpeechRecord]:
        records = []
        try:
            soup = self.soup(f"{self.base_url}/news-and-events/speeches.aspx")
        except Exception as e:
            logger.warning(f"[Boston] Page failed: {e}")
            return records

        year = str(date.today().year)
        seen_hrefs: set[str] = set()
        for row in soup.select("div.row"):
            link_el = row.select_one(f'h1.card-title a[href*="/speeches/{year}/"]')
            if not link_el:
                continue
            if link_el["href"] in seen_hrefs:
                continue
            seen_hrefs.add(link_el["href"])
            href = urljoin(self.base_url, link_el["href"])
            title = link_el.get_text(strip=True)

            speaker_el = row.select_one("ul.list-inline.speaker li a")
            speaker = speaker_el.get_text(strip=True).split(",")[0] if speaker_el else self.speaker_name

            date_el = row.select_one("p.date-and-location")
            speech_date = _parse_date_str(date_el.get_text(strip=True)) if date_el else None
            if not speech_date or not self.is_after_cutoff(speech_date):
                continue

            text = self._fetch_text(href)
            if not text:
                continue

            tier, voter = get_tier(speaker)
            records.append(SpeechRecord(
                speaker=speaker, date=speech_date, title=title,
                url=href, text=text, source=self.source_name,
                doc_type="speech", tier=tier, voter=voter,
            ))
        logger.info(f"[Boston] {len(records)} speeches")
        return records

    def _fetch_text(self, url: str) -> str:
        try:
            soup = self.soup(url)
            html_text = _clean_text(soup)
            # Boston speech pages serve the full text as a PDF; HTML page has only a brief summary
            if len(html_text) < 3000:
                pdf_link = soup.select_one('a[href*=".pdf"]')
                if pdf_link:
                    pdf_url = urljoin(self.base_url, pdf_link["href"])
                    logger.debug(f"[Boston] Fetching PDF: {pdf_url}")
                    return _fetch_pdf_text(pdf_url, self.session)
            return html_text
        except Exception as e:
            logger.warning(f"[Boston] Text fetch failed ({url}): {e}")
            return ""


# ---------------------------------------------------------------------------
# New York Fed
# ---------------------------------------------------------------------------
class NewYorkFedScraper(BaseScraper):
    """
    Structure: table > tr (one per speech)
      td.dirColL > div — date text ("Apr 21, 2026")
      td.dirColR > div.tablTitle > a.paraHeader — title + href
      Speaker: inferred from URL slug (e.g. "wil260416" → Williams)
    """
    source_name = "new_york"
    base_url = "https://www.newyorkfed.org"
    speaker_name = "John Williams"

    # Known URL slug prefixes for NY Fed speakers
    # The president is Williams ("wil"); all others are staff/researchers
    _SLUG_MAP = {
        "wil": "John Williams",
    }

    def fetch_speeches(self) -> list[SpeechRecord]:
        records = []
        try:
            soup = self.soup(f"{self.base_url}/newsevents/speeches")
        except Exception as e:
            logger.warning(f"[NY Fed] Page failed: {e}")
            return records

        for row in soup.select("tr"):
            date_el = row.select_one("td.dirColL div")
            link_el = row.select_one("td.dirColR a.paraHeader")
            if not date_el or not link_el:
                continue

            speech_date = _parse_date_str(date_el.get_text(strip=True))
            if not speech_date or not self.is_after_cutoff(speech_date):
                continue

            href = link_el["href"]
            if not href.startswith("http"):
                href = urljoin(self.base_url, href)

            # Infer speaker from URL slug prefix (e.g. "wil260416" → Williams)
            slug = href.rstrip("/").split("/")[-1]
            prefix = re.match(r"^([a-z]+)", slug)
            speaker_key = prefix.group(1) if prefix else ""
            speaker = self._SLUG_MAP.get(speaker_key)

            # Skip non-president speeches — staff/researcher talks are low signal
            if not speaker:
                continue

            text = self._fetch_text(href)
            if not text:
                continue

            tier, voter = get_tier(speaker)
            records.append(SpeechRecord(
                speaker=speaker, date=speech_date, title=link_el.get_text(strip=True),
                url=href, text=text, source=self.source_name,
                doc_type="speech", tier=tier, voter=voter,
            ))
        logger.info(f"[NY Fed] {len(records)} Williams speeches")
        return records

    def _fetch_text(self, url: str) -> str:
        try:
            return _clean_text(self.soup(url))
        except Exception as e:
            logger.warning(f"[NY Fed] Text fetch failed ({url}): {e}")
            return ""


# ---------------------------------------------------------------------------
# Philadelphia Fed  (DYNAMIC — no static listing available)
# ---------------------------------------------------------------------------
class PhiladelphiaFedScraper(BaseScraper):
    """
    URL: /the-economy/speeches-anna-paulson
    Structure: speeches are grouped under <h2>YEAR</h2> headers, then
    listed as bare <li> elements (not inside a named container class):
      <li>
        <a href="/the-economy/...">Title</a>
        | Month Day<br/>Event name
      </li>
    Date is assembled from the year in the preceding <h2> + "Month Day" in the <li> text.
    President: Anna Paulson (replaced Harker, 2026).
    """
    source_name = "philadelphia"
    base_url = "https://www.philadelphiafed.org"
    speaker_name = "Anna Paulson"

    def fetch_speeches(self) -> list[SpeechRecord]:
        records = []
        try:
            soup = self.soup(config.REGIONAL_FED_URLS["Philadelphia"])
        except Exception as e:
            logger.warning(f"[Philadelphia] Page failed: {e}")
            return records

        # Walk through h2 year headers and collect the <li> items under each
        current_year = None
        for el in soup.find_all(["h2", "li"]):
            if el.name == "h2":
                text = el.get_text(strip=True)
                if re.fullmatch(r"\d{4}", text):
                    current_year = int(text)
                continue

            if current_year is None:
                continue

            # A speech <li> has a direct <a href="/the-economy/..."> child
            link_el = el.find("a", href=lambda h: h and h.startswith("/the-economy/"))
            if not link_el:
                continue

            # Parse "| March 27" from the li text after the link
            li_text = el.get_text(separator=" ")
            m = re.search(
                r"\|\s*(January|February|March|April|May|June|July|August|"
                r"September|October|November|December)\s+(\d{1,2})",
                li_text, re.I,
            )
            if not m:
                continue
            try:
                speech_date = date(current_year, _MONTH_MAP[m.group(1).lower()], int(m.group(2)))
            except (ValueError, KeyError):
                continue

            if not self.is_after_cutoff(speech_date):
                continue

            href = urljoin(self.base_url, link_el["href"])
            text = self._fetch_text(href)
            if not text:
                continue

            tier, voter = get_tier(self.speaker_name)
            records.append(SpeechRecord(
                speaker=self.speaker_name,
                date=speech_date,
                title=link_el.get_text(strip=True),
                url=href, text=text, source=self.source_name,
                doc_type="speech", tier=tier, voter=voter,
            ))

        logger.info(f"[Philadelphia] {len(records)} Paulson speeches")
        return records

    def _fetch_text(self, url: str) -> str:
        try:
            return _clean_text(self.soup(url))
        except Exception as e:
            logger.warning(f"[Philadelphia] Text fetch failed ({url}): {e}")
            return ""


# ---------------------------------------------------------------------------
# Cleveland Fed  (DYNAMIC listing — individual pages work)
# ---------------------------------------------------------------------------
class ClevelandFedScraper(BaseScraper):
    """
    URL: /collections/speeches
    The listing is JS-rendered via Sitecore SXA; only the most recent speech
    link is visible in static HTML. Individual speech pages at
    /collections/speeches/YYYY/sp-YYYYMMDD-slug work fine.
    We collect whatever links are present in the static page.
    """
    source_name = "cleveland"
    base_url = "https://www.clevelandfed.org"
    speaker_name = "Beth Hammack"

    def fetch_speeches(self) -> list[SpeechRecord]:
        records = []
        try:
            soup = self.soup(config.REGIONAL_FED_URLS["Cleveland"])
        except Exception as e:
            logger.warning(f"[Cleveland] Page failed: {e}")
            return records

        year = str(date.today().year)
        seen = set()
        for a in soup.find_all("a", href=True):
            href = a["href"]
            if f"/collections/speeches/{year}/" not in href:
                continue
            full_url = urljoin(self.base_url, href) if not href.startswith("http") else href
            if full_url in seen:
                continue
            seen.add(full_url)

            # Date from URL slug: sp-20260306-...
            m = re.search(r"sp-(\d{8})-", full_url)
            if not m:
                continue
            ds = m.group(1)
            try:
                speech_date = date(int(ds[:4]), int(ds[4:6]), int(ds[6:8]))
            except ValueError:
                continue
            if not self.is_after_cutoff(speech_date):
                continue

            text = self._fetch_text(full_url)
            if not text:
                continue

            title = a.get_text(strip=True) or full_url.split("/")[-1].replace("-", " ").title()
            tier, voter = get_tier(self.speaker_name)
            records.append(SpeechRecord(
                speaker=self.speaker_name, date=speech_date, title=title,
                url=full_url, text=text, source=self.source_name,
                doc_type="speech", tier=tier, voter=voter,
            ))

        logger.info(
            f"[Cleveland] {len(records)} speech(es) — listing is JS-rendered "
            f"(Sitecore SXA); only statically-visible links captured"
        )
        return records

    def _fetch_text(self, url: str) -> str:
        try:
            return _clean_text(self.soup(url))
        except Exception as e:
            logger.warning(f"[Cleveland] Text fetch failed ({url}): {e}")
            return ""


# ---------------------------------------------------------------------------
# Richmond Fed
# ---------------------------------------------------------------------------
class RichmondFedScraper(BaseScraper):
    """
    Structure: div.data__row (one per speech)
      span.data__date                — "March 27, 2026"
      div.data__title > a            — title + href
      div.data__authors > p > a      — speaker name
    """
    source_name = "richmond"
    base_url = "https://www.richmondfed.org"
    speaker_name = "Thomas Barkin"

    def fetch_speeches(self) -> list[SpeechRecord]:
        records = []
        try:
            soup = self.soup(f"{self.base_url}/press_room/speeches")
        except Exception as e:
            logger.warning(f"[Richmond] Page failed: {e}")
            return records

        for row in soup.select("div.data__row"):
            date_el = row.select_one("span.data__date")
            link_el = row.select_one("div.data__title a")
            author_el = row.select_one("div.data__authors p a, div.data__authors p")
            if not date_el or not link_el:
                continue

            speech_date = _parse_date_str(date_el.get_text(strip=True))
            if not speech_date or not self.is_after_cutoff(speech_date):
                continue

            href = link_el["href"]
            if not href.startswith("http"):
                href = urljoin(self.base_url, href)

            speaker = author_el.get_text(strip=True).split(",")[0] if author_el else self.speaker_name
            text = self._fetch_text(href)
            if not text:
                continue

            tier, voter = get_tier(speaker)
            records.append(SpeechRecord(
                speaker=speaker, date=speech_date, title=link_el.get_text(strip=True),
                url=href, text=text, source=self.source_name,
                doc_type="speech", tier=tier, voter=voter,
            ))
        logger.info(f"[Richmond] {len(records)} speeches")
        return records

    def _fetch_text(self, url: str) -> str:
        try:
            return _clean_text(self.soup(url))
        except Exception as e:
            logger.warning(f"[Richmond] Text fetch failed ({url}): {e}")
            return ""


# ---------------------------------------------------------------------------
# Atlanta Fed
# ---------------------------------------------------------------------------
class AtlantaFedScraper(BaseScraper):
    """
    Speeches are embedded as a JSON array in a <script> block:
      var feed_XYZ = [{Title, Date, Authors:[{FullName}], Url, FormattedDate}]
    """
    source_name = "atlanta"
    base_url = "https://www.atlantafed.org"
    speaker_name = "Raphael Bostic"

    def fetch_speeches(self) -> list[SpeechRecord]:
        records = []
        try:
            soup = self.soup(config.REGIONAL_FED_URLS["Atlanta"])
        except Exception as e:
            logger.warning(f"[Atlanta] Page failed: {e}")
            return records

        items = self._extract_json_items(soup)
        logger.info(f"[Atlanta] {len(items)} items in embedded JSON")

        for item in items:
            raw_date = item.get("Date", "")
            speech_date = _parse_date_str(raw_date[:10]) if raw_date else None
            if not speech_date or not self.is_after_cutoff(speech_date):
                continue

            url_path = item.get("Url", "")
            if not url_path:
                continue
            href = url_path if url_path.startswith("http") else urljoin(self.base_url, url_path)

            # Atlanta links to external media (YouTube, Bloomberg, WABE, etc.)
            # Only scrape pages on atlantafed.org; YouTube is handled by YouTubeScraper
            if "atlantafed.org" not in href:
                if "youtube.com" in href:
                    logger.debug(f"[Atlanta] YouTube URL queued for YouTube scraper: {href}")
                else:
                    logger.debug(f"[Atlanta] Skipping external media URL: {href}")
                continue

            authors = item.get("Authors", [])
            # Use speaker from JSON so the scraper automatically picks up new presidents
            raw_speaker = authors[0].get("FullName", "") if authors else ""
            speaker = re.sub(r"\s+", " ", raw_speaker).split(",")[0].strip() or self.speaker_name

            # Strip HTML tags from title
            raw_title = item.get("Title", "")
            title = BeautifulSoup(raw_title, "lxml").get_text(strip=True)

            text = self._fetch_text(href)
            if not text:
                continue

            tier, voter = get_tier(speaker)
            records.append(SpeechRecord(
                speaker=speaker, date=speech_date, title=title,
                url=href, text=text, source=self.source_name,
                doc_type="speech", tier=tier, voter=voter,
            ))

        if not records:
            logger.info("[Atlanta] No atlantafed.org speech transcripts found — "
                        "speeches are hosted on external media. Use YouTube scraper for video appearances.")
        return records

    def _extract_json_items(self, soup: BeautifulSoup) -> list[dict]:
        for script in soup.find_all("script"):
            txt = script.string or ""
            m = re.search(r"var\s+\w+\s*=\s*(\[.*?\]);", txt, re.DOTALL)
            if not m:
                continue
            try:
                arr = json.loads(m.group(1))
                if arr and isinstance(arr[0], dict) and "Title" in arr[0]:
                    return arr
            except (json.JSONDecodeError, IndexError):
                continue
        return []

    def _fetch_text(self, url: str) -> str:
        try:
            return _clean_text(self.soup(url))
        except Exception as e:
            logger.warning(f"[Atlanta] Text fetch failed ({url}): {e}")
            return ""


# ---------------------------------------------------------------------------
# Chicago Fed  (DYNAMIC — no working listing page)
# ---------------------------------------------------------------------------
class ChicagoFedScraper(BaseScraper):
    """
    URL: /utilities/about-us/office-of-the-president/office-of-the-president-speaking
    Structure: div.cyan-publication (one per speech)
      a[href]                  — title + link to /publications/speeches/YYYY/slug
      p.cyan-publication-date  — "May 12, 2026"
    """
    source_name = "chicago"
    base_url = "https://www.chicagofed.org"
    speaker_name = "Austan Goolsbee"

    def fetch_speeches(self) -> list[SpeechRecord]:
        records = []
        try:
            soup = self.soup(config.REGIONAL_FED_URLS["Chicago"])
        except Exception as e:
            logger.warning(f"[Chicago] Page failed: {e}")
            return records

        year = str(date.today().year)
        for card in soup.select("div.cyan-publication"):
            link_el = card.find("a", href=True)
            if not link_el:
                continue
            href = link_el["href"]
            if f"/speeches/{year}/" not in href:
                continue
            full_url = href if href.startswith("http") else f"{self.base_url}{href}"

            date_el = card.select_one("p.cyan-publication-date")
            speech_date = _parse_date_str(date_el.get_text(strip=True)) if date_el else None
            if not speech_date:
                speech_date = self._date_from_slug(href)
            if not speech_date or not self.is_after_cutoff(speech_date):
                continue

            text = self._fetch_text(full_url)
            if not text:
                continue

            tier, voter = get_tier(self.speaker_name)
            records.append(SpeechRecord(
                speaker=self.speaker_name,
                date=speech_date,
                title=link_el.get_text(strip=True),
                url=full_url, text=text, source=self.source_name,
                doc_type="speech", tier=tier, voter=voter,
            ))

        logger.info(f"[Chicago] {len(records)} Goolsbee speeches")
        return records

    def _fetch_text(self, url: str) -> str:
        try:
            soup = self.soup(url)
            for tag in soup.select("nav, header, footer, script, style, .breadcrumb"):
                tag.decompose()
            content = (
                soup.select_one("div.cfedContent__text")
                or soup.select_one("div.cfedContent__body")
                or soup.find("main")
            )
            html_text = content.get_text(separator="\n", strip=True) if content else ""
            # Chicago speeches are often PDFs linked from the page
            if len(html_text) < 500:
                pdf_link = soup.select_one('a[href*=".pdf"]')
                if pdf_link:
                    pdf_url = pdf_link["href"]
                    if not pdf_url.startswith("http"):
                        pdf_url = f"{self.base_url}{pdf_url}"
                    logger.debug(f"[Chicago] Fetching PDF: {pdf_url}")
                    return _fetch_pdf_text(pdf_url, self.session)
            return html_text
        except Exception as e:
            logger.warning(f"[Chicago] Text fetch failed ({url}): {e}")
            return ""

    def _date_from_slug(self, href: str) -> date | None:
        m = re.search(r"/speeches/(\d{4})/([a-z]+)-(\d{1,2})-", href)
        if not m:
            return None
        month = _MONTH_MAP.get(m.group(2).lower())
        if not month:
            return None
        try:
            return date(int(m.group(1)), month, int(m.group(3)))
        except ValueError:
            return None


# ---------------------------------------------------------------------------
# St. Louis Fed  (DYNAMIC — JS-rendered)
# ---------------------------------------------------------------------------
class StLouisFedScraper(BaseScraper):
    """
    URL: /from-the-president/remarks
    The page uses Sitecore SXA search at endpoint //sxa/search/results/
    The search component signature is "srremarks" and auto-fires on load.
    We call the API directly to get speech listings.
    """
    source_name = "st_louis"
    base_url = "https://www.stlouisfed.org"
    speaker_name = "Alberto Musalem"

    def fetch_speeches(self) -> list[SpeechRecord]:
        records = []
        try:
            data = self._call_sxa_api()
        except Exception as e:
            logger.warning(f"[St. Louis] SXA API failed: {e}")
            return records

        for item in data:
            result = self._parse_item(item)
            if result is None:
                continue
            speech_date, full_url, html_text = result
            if not speech_date or not self.is_after_cutoff(speech_date):
                continue

            # Extract title from Html text (first quoted phrase or first sentence)
            title_m = re.search(r'["“]([^"”]{10,120})["”]', html_text)
            title = title_m.group(1).strip() if title_m else html_text[:80].strip()

            text = self._fetch_text(full_url)
            if not text:
                continue

            tier, voter = get_tier(self.speaker_name)
            records.append(SpeechRecord(
                speaker=self.speaker_name,
                date=speech_date,
                title=title,
                url=full_url, text=text, source=self.source_name,
                doc_type="speech", tier=tier, voter=voter,
            ))

        logger.info(f"[St. Louis] {len(records)} Musalem speeches")
        return records

    def _call_sxa_api(self) -> list[dict]:
        # Sitecore SXA search — scope GUID narrows to /from-the-president/remarks subtree.
        # Note: as of 2026-04 the index only contains entries through Nov 2024;
        # St. Louis publishes new speeches asynchronously. Scraper will pick them
        # up once they are indexed.
        api_url = f"{self.base_url}/sxa/search/results/"
        all_results = []
        page_size = 20
        offset = 0
        while True:
            params = {
                "sig":    "srremarks",
                "itemid": "{171B272E-9D98-430F-9F07-825319267544}",
                "s":      "{DA5A2E95-2DA8-48EF-8A05-C6C4DEE314B1}",
                "v":      "{073ED7F6-4F06-4C6D-9FF4-09BD85939FDC}",
                "p":      page_size,
                "o":      offset,
                "l":      "",
            }
            resp = self.session.get(api_url, params=params, timeout=20)
            resp.raise_for_status()
            payload = resp.json()
            batch = payload.get("Results") or []
            all_results.extend(batch)
            if len(batch) < page_size:
                break
            offset += page_size
        return all_results

    def _parse_item(self, item: dict) -> SpeechRecord | None:
        url_path = item.get("Url", "")
        if not url_path:
            return None
        full_url = urljoin(self.base_url, url_path)

        # Extract date from rendered Html: "(Nov. 13, 2024)" pattern
        html = item.get("Html", "")
        text_plain = BeautifulSoup(html, "lxml").get_text()
        m = re.search(
            r"\((\w+\.?\s+\d{1,2},\s+\d{4})\)",
            text_plain,
        )
        speech_date = _parse_date_str(m.group(1)) if m else None

        # Fallback: year from URL path /remarks/YYYY/slug
        if not speech_date:
            ym = re.search(r"/remarks/(\d{4})/", url_path)
            if ym:
                speech_date = date(int(ym.group(1)), 1, 1)  # year only — day unknown

        return speech_date, full_url, text_plain

    def _fetch_text(self, url: str) -> str:
        try:
            return _clean_text(self.soup(url))
        except Exception as e:
            logger.warning(f"[St. Louis] Text fetch failed ({url}): {e}")
            return ""


# ---------------------------------------------------------------------------
# Minneapolis Fed
# ---------------------------------------------------------------------------
class MinneapolisFedScraper(BaseScraper):
    """
    The listing page is Next.js/dynamic but the person page for Kashkari
    at /people/neel-kashkari exposes speech links in static HTML.
    Pattern: /speeches/YYYY/slug
    """
    source_name = "minneapolis"
    base_url = "https://www.minneapolisfed.org"
    speaker_name = "Neel Kashkari"

    def fetch_speeches(self) -> list[SpeechRecord]:
        records = []
        try:
            soup = self.soup(f"{self.base_url}/people/neel-kashkari")
        except Exception as e:
            logger.warning(f"[Minneapolis] Person page failed: {e}")
            return records

        year = str(date.today().year)
        seen = set()
        for a in soup.find_all("a", href=True):
            href = a["href"]
            if f"/speeches/{year}/" not in href:
                continue
            if not href.startswith("http"):
                href = urljoin(self.base_url, href)
            if href in seen:
                continue
            seen.add(href)

            title = a.get_text(strip=True)

            # Date from URL slug: /speeches/2026/slug-MMDD or from speech page
            speech_date = self._date_from_slug(href) or self._date_from_page(href)
            if not speech_date or not self.is_after_cutoff(speech_date):
                continue

            text = self._fetch_text(href)
            if not text:
                continue

            tier, voter = get_tier(self.speaker_name)
            records.append(SpeechRecord(
                speaker=self.speaker_name, date=speech_date, title=title,
                url=href, text=text, source=self.source_name,
                doc_type="speech", tier=tier, voter=voter,
            ))

        logger.info(f"[Minneapolis] {len(records)} speeches")
        return records

    def _date_from_slug(self, url: str) -> date | None:
        m = re.search(r"/(\d{4})/\S*?(\d{4})-(\d{2})-(\d{2})", url)
        if m:
            try:
                return date(int(m.group(2)), int(m.group(3)), int(m.group(4)))
            except ValueError:
                pass
        return None

    def _date_from_page(self, url: str) -> date | None:
        try:
            soup = self.soup(url)
            for el in soup.find_all(["time", "span", "p"], class_=re.compile(r"date|time", re.I)):
                d = _parse_date_str(el.get_text(strip=True))
                if d:
                    return d
        except Exception:
            pass
        return None

    def _fetch_text(self, url: str) -> str:
        try:
            return _clean_text(self.soup(url))
        except Exception as e:
            logger.warning(f"[Minneapolis] Text fetch failed ({url}): {e}")
            return ""


# ---------------------------------------------------------------------------
# Kansas City Fed
# ---------------------------------------------------------------------------
class KansasCityFedScraper(BaseScraper):
    """
    Structure: div.card (one per speech or PDF)
      span.date > time[datetime]   — ISO date
      div.body > h3 > a            — title + href
      div.body > p                 — speaker description

    Filter: skip cards that link to PDFs (staff economists, not Schmid).
    Schmid's speeches link to HTML pages at /speeches/slug/.
    """
    source_name = "kansas_city"
    base_url = "https://www.kansascityfed.org"
    speaker_name = "Jeff Schmid"

    def fetch_speeches(self) -> list[SpeechRecord]:
        records = []
        try:
            # Page is ~620KB; stream it to avoid mid-download timeout
            with self.session.get(f"{self.base_url}/speeches", timeout=120, stream=True) as resp:
                resp.raise_for_status()
                chunks = []
                for chunk in resp.iter_content(32768):
                    chunks.append(chunk)
                html = b"".join(chunks).decode("utf-8", errors="replace")
            soup = BeautifulSoup(html, "lxml")
        except Exception as e:
            logger.warning(f"[Kansas City] Page failed: {e}")
            return records

        for card in soup.select("div.card"):
            time_el = card.select_one("time[datetime]")
            if not time_el:
                continue
            speech_date = _parse_date_str(time_el.get("datetime", ""))
            if not speech_date or not self.is_after_cutoff(speech_date):
                continue

            link_el = card.select_one("div.body h3 a, div.body a")
            if not link_el:
                continue
            href = link_el["href"]
            if not href.startswith("http"):
                href = urljoin(self.base_url, href)

            # Skip PDF links — those are staff economists, not the president
            if href.lower().endswith(".pdf"):
                continue

            speaker_el = card.select_one("div.body p")
            # The speaker paragraph often starts with "The following remarks are from Jeff Schmid"
            raw_speaker = speaker_el.get_text(strip=True) if speaker_el else ""
            if "Schmid" in raw_speaker or not raw_speaker:
                speaker = self.speaker_name
            else:
                continue  # skip non-Schmid HTML speeches

            text = self._fetch_text(href)
            if not text:
                continue

            tier, voter = get_tier(speaker)
            records.append(SpeechRecord(
                speaker=speaker, date=speech_date, title=link_el.get_text(strip=True),
                url=href, text=text, source=self.source_name,
                doc_type="speech", tier=tier, voter=voter,
            ))

        logger.info(f"[Kansas City] {len(records)} Schmid speeches")
        return records

    def _fetch_text(self, url: str) -> str:
        try:
            return _clean_text(self.soup(url))
        except Exception as e:
            logger.warning(f"[Kansas City] Text fetch failed ({url}): {e}")
            return ""


# ---------------------------------------------------------------------------
# Dallas Fed
# ---------------------------------------------------------------------------
class DallasFedScraper(BaseScraper):
    """
    URL: /news/speeches/logan
    Structure: year-tab divs div.tab-pane.dal-tab__pane[id=YYYY], each containing
    <p> elements. First <a> in each <p> that matches /news/speeches/logan/YYYY/lkl*
    is the speech. Date is in the <p> text ("April 2, 2026").
    """
    source_name = "dallas"
    base_url = "https://www.dallasfed.org"
    speaker_name = "Lorie Logan"

    def fetch_speeches(self) -> list[SpeechRecord]:
        records = []
        try:
            soup = self.soup(f"{self.base_url}/news/speeches/logan")
        except Exception as e:
            logger.warning(f"[Dallas] Page failed: {e}")
            return records

        year = str(date.today().year)
        # Find the current year's tab pane
        tab = soup.find("div", id=year, class_=re.compile(r"tab-pane"))
        if not tab:
            # Fallback: search all tab panes
            tab = soup

        seen = set()
        for p in tab.find_all("p"):
            # First link in the <p> that is a speech page
            link_el = p.find(
                "a",
                href=lambda h: h and re.search(r"/news/speeches/logan/\d{4}/lkl", h),
            )
            if not link_el:
                continue
            href = link_el["href"]
            if not href.startswith("http"):
                href = urljoin(self.base_url, href)
            if href in seen:
                continue
            seen.add(href)

            title = link_el.get_text(strip=True)

            # Date from paragraph text: "April 2, 2026" or "Jan. 29, 2026"
            p_text = p.get_text(separator=" ")
            speech_date = _parse_date_str(
                re.search(
                    r"(January|February|March|April|May|June|July|August|"
                    r"September|October|November|December|Jan|Feb|Mar|Apr|"
                    r"Jun|Jul|Aug|Sep|Oct|Nov|Dec)\.?\s+\d{1,2},\s+\d{4}",
                    p_text,
                ).group(0)
                if re.search(
                    r"(January|February|March|April|May|June|July|August|"
                    r"September|October|November|December|Jan|Feb|Mar|Apr|"
                    r"Jun|Jul|Aug|Sep|Oct|Nov|Dec)\.?\s+\d{1,2},\s+\d{4}",
                    p_text,
                )
                else ""
            )
            # Fallback: date from URL slug lkl260402 → 2026-04-02
            if not speech_date:
                m = re.search(r"lkl(\d{2})(\d{2})(\d{2})", href)
                if m:
                    try:
                        speech_date = date(2000 + int(m.group(1)), int(m.group(2)), int(m.group(3)))
                    except ValueError:
                        pass

            if not speech_date or not self.is_after_cutoff(speech_date):
                continue

            text = self._fetch_text(href)
            if not text:
                continue

            tier, voter = get_tier(self.speaker_name)
            records.append(SpeechRecord(
                speaker=self.speaker_name,
                date=speech_date,
                title=title,
                url=href, text=text, source=self.source_name,
                doc_type="speech", tier=tier, voter=voter,
            ))

        logger.info(f"[Dallas] {len(records)} Logan speeches")
        return records

    def _fetch_text(self, url: str) -> str:
        try:
            return _clean_text(self.soup(url))
        except Exception as e:
            logger.warning(f"[Dallas] Text fetch failed ({url}): {e}")
            return ""


# ---------------------------------------------------------------------------
# San Francisco Fed
# ---------------------------------------------------------------------------
class SanFranciscoFedScraper(BaseScraper):
    """
    Speaker page: /news-and-media/speeches/mary-c-daly
    Structure: li.wp-block-post > h2.wp-block-post-title > a (title + href)
    Date: from the speech page itself (no date in list HTML).
    """
    source_name = "san_francisco"
    base_url = "https://www.frbsf.org"
    speaker_name = "Mary Daly"
    list_url = "https://www.frbsf.org/news-and-media/speeches/mary-c-daly"

    def fetch_speeches(self) -> list[SpeechRecord]:
        records = []
        try:
            soup = self.soup(self.list_url)
        except Exception as e:
            logger.warning(f"[SF Fed] Page failed: {e}")
            return records

        for li in soup.select("li.wp-block-post"):
            link_el = li.select_one("h2.wp-block-post-title a, a[href]")
            if not link_el:
                continue
            href = link_el["href"]
            if not href.startswith("http"):
                href = urljoin(self.base_url, href)
            title = link_el.get_text(strip=True)

            # Fetch speech page to get date and text
            try:
                speech_soup = self.soup(href)
            except Exception:
                continue

            date_el = speech_soup.select_one("time[datetime], span.entry-date, p.date")
            speech_date = None
            if date_el:
                speech_date = _parse_date_str(
                    date_el.get("datetime", "") or date_el.get_text(strip=True)
                )
            if not speech_date:
                # Try to extract from URL: /2026/04/slug/
                m = re.search(r"/(\d{4})/(\d{2})/", href)
                if m:
                    try:
                        speech_date = date(int(m.group(1)), int(m.group(2)), 1)
                    except ValueError:
                        pass
            if not speech_date or not self.is_after_cutoff(speech_date):
                continue

            text = _clean_text(speech_soup)
            if not text:
                continue

            tier, voter = get_tier(self.speaker_name)
            records.append(SpeechRecord(
                speaker=self.speaker_name, date=speech_date, title=title,
                url=href, text=text, source=self.source_name,
                doc_type="speech", tier=tier, voter=voter,
            ))

        logger.info(f"[SF Fed] {len(records)} Daly speeches")
        return records


# ---------------------------------------------------------------------------
# Factory
# ---------------------------------------------------------------------------
ALL_REGIONAL_SCRAPERS: list[type[BaseScraper]] = [
    BostonFedScraper,
    NewYorkFedScraper,
    PhiladelphiaFedScraper,
    ClevelandFedScraper,
    RichmondFedScraper,
    AtlantaFedScraper,
    ChicagoFedScraper,
    StLouisFedScraper,
    MinneapolisFedScraper,
    KansasCityFedScraper,
    DallasFedScraper,
    SanFranciscoFedScraper,
]
