"""
Collect all FOMC cycle documents (statements, minutes, press conferences)
for 2021-2026. Saves to data/raw/{statements,minutes,pressconferences}/.

Run: python3 collect_fomc_historical.py
"""

import io
import logging
import ssl
import time
import urllib.request
from pathlib import Path

import requests
from bs4 import BeautifulSoup

try:
    from pdfminer.high_level import extract_text as pdf_extract
except ImportError:
    pdf_extract = None

BASE = Path(__file__).parent
STMT_DIR  = BASE / "data/raw/statements"
MIN_DIR   = BASE / "data/raw/minutes"
PCONF_DIR = BASE / "data/raw/pressconferences"
LOG_FILE  = BASE / "logs/collect_fomc_historical.log"
LOG_FILE.parent.mkdir(exist_ok=True)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(message)s",
    handlers=[
        logging.FileHandler(LOG_FILE),
        logging.StreamHandler(),
    ],
)
log = logging.getLogger(__name__)

HEADERS = {"User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36"}
DELAY   = 2.5  # seconds between requests

# ── FOMC meeting dates (statement release date = last day of meeting) ──────────
# Verified from federalreserve.gov/monetarypolicy/fomccalendars.htm
MEETINGS = [
    # 2021
    "20210127", "20210317", "20210428", "20210616",
    "20210728", "20210922", "20211103", "20211215",
    # 2022
    "20220126", "20220316", "20220504", "20220615",
    "20220727", "20220921", "20221102", "20221214",
    # 2023
    "20230201", "20230322", "20230503", "20230614",
    "20230726", "20230920", "20231101", "20231213",
    # 2024
    "20240131", "20240320", "20240501", "20240612",
    "20240731", "20240918", "20241107", "20241218",
    # 2025
    "20250129", "20250319", "20250507", "20250618",
    "20250730", "20250917", "20251029", "20251210",
    # 2026 (through April 29; June 16-17 not yet released)
    "20260128", "20260318", "20260429",
]

# ── URL templates ──────────────────────────────────────────────────────────────
def stmt_url(d):
    return f"https://www.federalreserve.gov/newsevents/pressreleases/monetary{d}a.htm"

def min_url(d):
    return f"https://www.federalreserve.gov/monetarypolicy/fomcminutes{d}.htm"

def pconf_url(d):
    return f"https://www.federalreserve.gov/mediacenter/files/FOMCpresconf{d}.pdf"

def pconf_page_url(d):
    return f"https://www.federalreserve.gov/monetarypolicy/fomcpresconf{d}.htm"


# ── Helpers ────────────────────────────────────────────────────────────────────
def fetch_html(url, retries=3):
    for attempt in range(retries):
        try:
            r = requests.get(url, headers=HEADERS, timeout=30, verify=False)
            if r.status_code == 200:
                return r.text
            log.warning(f"HTTP {r.status_code}: {url}")
            return None
        except Exception as e:
            log.warning(f"Attempt {attempt+1} failed for {url}: {e}")
            time.sleep(3)
    return None


def fetch_pdf_text(url, retries=3):
    if pdf_extract is None:
        log.error("pdfminer not installed; cannot extract PDF text")
        return None
    ssl_ctx = ssl._create_unverified_context()
    for attempt in range(retries):
        try:
            req = urllib.request.Request(url, headers=HEADERS)
            with urllib.request.urlopen(req, context=ssl_ctx, timeout=60) as resp:
                data = resp.read()
            if len(data) < 5000:
                log.warning(f"PDF too small ({len(data)}B): {url}")
                return None
            text = pdf_extract(io.BytesIO(data))
            return text.strip() if text else None
        except Exception as e:
            log.warning(f"PDF attempt {attempt+1} failed for {url}: {e}")
            time.sleep(3)
    return None


def html_to_text(html, url):
    soup = BeautifulSoup(html, "html.parser")
    # Try known content divs
    for sel in ["#article", ".col-xs-12.col-sm-8", ".article", "article"]:
        el = soup.select_one(sel)
        if el:
            return el.get_text(separator="\n").strip()
    return soup.get_text(separator="\n").strip()


def is_valid_content(text, doctype):
    """Reject pages that are error pages, redirects, or SLRG reaffirmations."""
    if not text or len(text) < 300:
        return False
    bad_phrases = [
        "Statement on Longer-Run Goals and Monetary Policy Strategy",
        "reaffirms its",
        "page not found",
        "error",
    ]
    low = text.lower()
    for phrase in bad_phrases:
        if phrase.lower() in low[:500]:
            log.warning(f"  Rejected: contains '{phrase}'")
            return False
    return True


def save(path, source_url, text):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(f"SOURCE: {source_url}\n\n{text}", encoding="utf-8")


# ── Per-document collectors ────────────────────────────────────────────────────
def collect_statement(date):
    outpath = STMT_DIR / f"{date}_FOMC_Statement.txt"
    if outpath.exists():
        log.info(f"  [STMT] {date} — already exists, skipping")
        return True

    url = stmt_url(date)
    html = fetch_html(url)
    if not html:
        log.error(f"  [STMT] {date} — fetch failed")
        return False

    text = html_to_text(html, url)
    if not is_valid_content(text, "statement"):
        log.error(f"  [STMT] {date} — invalid content")
        return False

    save(outpath, url, text)
    log.info(f"  [STMT] {date} — saved ({len(text)} chars)")
    return True


def collect_minutes(date):
    outpath = MIN_DIR / f"{date}_FOMC_Minutes.txt"
    if outpath.exists():
        log.info(f"  [MIN]  {date} — already exists, skipping")
        return True

    url = min_url(date)
    html = fetch_html(url)
    if not html:
        log.error(f"  [MIN]  {date} — fetch failed")
        return False

    text = html_to_text(html, url)
    if not is_valid_content(text, "minutes"):
        log.error(f"  [MIN]  {date} — invalid content")
        return False

    save(outpath, url, text)
    log.info(f"  [MIN]  {date} — saved ({len(text)} chars)")
    return True


def collect_pressconf(date):
    outpath = PCONF_DIR / f"{date}_FOMC_Pressconf.txt"
    if outpath.exists():
        log.info(f"  [PCONF] {date} — already exists, skipping")
        return True

    # Press conferences only exist from April 2011 onward; quarterly until 2019,
    # then all meetings. For 2021+ all meetings have one.
    url = pconf_url(date)
    text = fetch_pdf_text(url)

    if not text or len(text) < 1000:
        log.warning(f"  [PCONF] {date} — PDF failed or too short; trying page scrape")
        # Some older conferences have transcript on the page itself
        page_html = fetch_html(pconf_page_url(date))
        if page_html:
            text = html_to_text(page_html, pconf_page_url(date))
            if len(text) < 1000:
                log.error(f"  [PCONF] {date} — no usable transcript found")
                return False
            url = pconf_page_url(date)
        else:
            log.error(f"  [PCONF] {date} — all methods failed")
            return False

    save(outpath, url, text)
    log.info(f"  [PCONF] {date} — saved ({len(text)} chars)")
    return True


# ── Main ───────────────────────────────────────────────────────────────────────
def main():
    log.info("=" * 60)
    log.info("FOMC historical collection starting")
    log.info(f"Meetings to process: {len(MEETINGS)}")
    log.info("=" * 60)

    results = {"stmt": 0, "min": 0, "pconf": 0, "errors": 0}

    for i, date in enumerate(MEETINGS, 1):
        log.info(f"\n[{i}/{len(MEETINGS)}] Meeting: {date}")

        # Statement
        time.sleep(DELAY)
        ok = collect_statement(date)
        if ok:
            results["stmt"] += 1
        else:
            results["errors"] += 1

        # Minutes
        time.sleep(DELAY)
        ok = collect_minutes(date)
        if ok:
            results["min"] += 1
        else:
            results["errors"] += 1

        # Press conference
        time.sleep(DELAY)
        ok = collect_pressconf(date)
        if ok:
            results["pconf"] += 1
        else:
            results["errors"] += 1

    log.info("\n" + "=" * 60)
    log.info("Collection complete")
    log.info(f"  Statements:       {results['stmt']}/{len(MEETINGS)}")
    log.info(f"  Minutes:          {results['min']}/{len(MEETINGS)}")
    log.info(f"  Press conferences:{results['pconf']}/{len(MEETINGS)}")
    log.info(f"  Errors/skipped:   {results['errors']}")
    log.info(f"  Log: {LOG_FILE}")
    log.info("=" * 60)


if __name__ == "__main__":
    import warnings
    warnings.filterwarnings("ignore")
    main()
