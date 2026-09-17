"""
Collect every Summary of Economic Projections (SEP / "dot plot") release,
October 2007 to present, from federalreserve.gov.

Three layers exist per projection meeting, and they differ by era:

  1. Projection materials (the public "dot plot" release, 2:00pm with the
     statement)
       HTML  /monetarypolicy/fomcprojtabl{YYYYMMDD}.htm        (Jan 2012 →)
       PDF   /monetarypolicy/files/fomcprojtabl{YYYYMMDD}.pdf  (Apr 2011 →)
     Before April 2011 the SEP was published only with the minutes (layer 2).

  2. SEP addendum to the minutes — the full narrative + Table 1 + accessible
     figure data. Separate page for every SEP Oct 2007 → Sept 2020; from Dec
     2020 the same text is embedded in the minutes page itself, which
     collect_fomc_historical.py already saves to data/raw/minutes/.
       HTML  /monetarypolicy/fomcminutes{YYYYMMDD}ep.htm   (2007 → Sept 2020)
       HTML  /monetarypolicy/fomcminutes{YYYYMMDD}epa.htm  (accessible figure data, where present)

  3. Individual projections ("SEP: Individual Projections" compilation) and the
     participant key. Released with the 5-year-lag transcripts, so they exist
     only through the year the transcripts cover (2020 as of Sept 2026).
       PDF   /monetarypolicy/files/FOMC{YYYYMMDD}SEPcompilation.pdf
       PDF   /monetarypolicy/files/FOMC{YYYYMMDD}SEPkey.pdf

Output
  data/raw/sep/{d}_SEP_projections.txt        layer 1 as table-aware text  (committed)
  data/raw/sep/{d}_SEP_minutes_addendum.txt   layer 2 as table-aware text  (committed)
  data/raw/sep/{d}_SEP_minutes_addendum_figures.txt  layer 2 accessible figure
                                              data page, where one exists (2007–2014)
  data/historical/raw/sep/projtabl/           layer 1 PDFs                 (gitignored)
  data/historical/raw/sep/individual/         layer 3 PDFs + extracted txt (gitignored)

Every text file starts with `SOURCE: <url>` (provenance guard requirement).
Already-saved files are skipped, so the script is safe to re-run after each
new projection meeting.

Run: python3 collect_sep_historical.py [--dates 20260916,...] [--no-pdf]
"""

import argparse
import io
import logging
import re
import ssl
import time
import urllib.request
from pathlib import Path

import requests
import urllib3
from bs4 import BeautifulSoup, NavigableString

try:
    from pdfminer.high_level import extract_text as pdf_extract
except ImportError:
    pdf_extract = None

urllib3.disable_warnings()

BASE = Path(__file__).parent
TXT_DIR = BASE / "data/raw/sep"
PDF_DIR = BASE / "data/historical/raw/sep/projtabl"
IND_DIR = BASE / "data/historical/raw/sep/individual"
LOG_FILE = BASE / "logs/collect_sep_historical.log"
LOG_FILE.parent.mkdir(exist_ok=True)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(message)s",
    handlers=[logging.FileHandler(LOG_FILE), logging.StreamHandler()],
)
log = logging.getLogger(__name__)

FED = "https://www.federalreserve.gov"
HEADERS = {"User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36"}
DELAY = 1.5

# Era boundaries (verified by probing the site, Sept 2026)
FIRST_PROJTABL_PDF = "20110427"   # SEP first released with the statement
FIRST_PROJTABL_HTM = "20120125"   # first accessible HTML projection page (and first dot plot)
LAST_COMPILATION = "20201216"     # individual projections lag 5 years
LAST_EP_ADDENDUM = "20200916"     # from Dec 2020 the SEP narrative is embedded in the
                                  # minutes page itself (data/raw/minutes/), no separate ep page

# Fallback list — every projection meeting Oct 2007 → Sept 2026. Used only if
# the index pages cannot be fetched. Note 2020-03-15 had no SEP (cancelled).
SEP_DATES_FALLBACK = """
20071031 20080130 20080430 20080625 20081029 20090128 20090429 20090624 20091104
20100127 20100428 20100623 20101103 20110126 20110427 20110622 20111102
20120125 20120425 20120620 20120913 20121212 20130320 20130619 20130918 20131218
20140319 20140618 20140917 20141217 20150318 20150617 20150917 20151216
20160316 20160615 20160921 20161214 20170315 20170614 20170920 20171213
20180321 20180613 20180926 20181219 20190320 20190619 20190918 20191211
20200610 20200916 20201216 20210317 20210616 20210922 20211215
20220316 20220615 20220921 20221214 20230322 20230614 20230920 20231213
20240320 20240612 20240918 20241218 20250319 20250618 20250917 20251210
20260318 20260617 20260916
""".split()


# ── Fetch helpers ──────────────────────────────────────────────────────────────
def fetch(url, retries=3, binary=False):
    """GET a URL. Returns text (or bytes if binary) on 200, None on 404/other."""
    for attempt in range(retries):
        try:
            r = requests.get(url, headers=HEADERS, timeout=60, verify=False)
            if r.status_code == 200:
                if binary:
                    return r.content
                # Fed pages omit a charset header: modern pages are UTF-8,
                # pre-2011 pages are windows-1252.
                try:
                    return r.content.decode("utf-8")
                except UnicodeDecodeError:
                    return r.content.decode("cp1252", errors="replace")
            if r.status_code == 404:
                return None
            log.warning(f"HTTP {r.status_code}: {url}")
        except Exception as e:
            log.warning(f"Attempt {attempt + 1} failed for {url}: {e}")
        time.sleep(3)
    return None


def discover_dates():
    """Derive the projection-meeting list from the Fed's own index pages.

    2021→ : fomccalendars.htm links fomcprojtabl{d}.htm / .pdf
    2007–2020: fomchistorical{YYYY}.htm links FOMC{d}SEPcompilation.pdf
    """
    dates = set()
    cal = fetch(f"{FED}/monetarypolicy/fomccalendars.htm")
    if cal:
        dates.update(re.findall(r"fomcprojtabl(\d{8})", cal))
    time.sleep(DELAY)
    for y in range(2007, 2021):
        page = fetch(f"{FED}/monetarypolicy/fomchistorical{y}.htm")
        if page:
            dates.update(re.findall(r"FOMC(\d{8})SEPcompilation", page))
        time.sleep(0.5)
    if not dates:
        log.warning("Index discovery failed — using hardcoded fallback list")
        return sorted(SEP_DATES_FALLBACK)
    missing = sorted(set(SEP_DATES_FALLBACK) - dates)
    if missing:
        log.warning(f"Index pages lack {missing}; adding from fallback list")
        dates.update(missing)
    return sorted(dates)


# ── HTML → text with tables preserved ─────────────────────────────────────────
def table_to_text(table):
    rows = []
    for tr in table.find_all("tr"):
        cells = [c.get_text(" ", strip=True) for c in tr.find_all(["th", "td"])]
        if any(cells):
            rows.append(" | ".join(cells))
    cap = table.find("caption")
    head = f"[TABLE] {cap.get_text(' ', strip=True)}\n" if cap else "[TABLE]\n"
    return "\n" + head + "\n".join(rows) + "\n[/TABLE]\n"


def html_to_text(html):
    soup = BeautifulSoup(html, "html.parser")
    for tag in soup(["script", "style", "nav", "header", "footer"]):
        tag.decompose()
    # Old-layout (pre-2011) pages carry nav tables with ids — drop them.
    for tid in ("headerTopLinks", "navMenu", "footerNav"):
        for t in soup.find_all("table", id=tid):
            t.decompose()
    for t in soup.find_all("table"):
        t.replace_with(NavigableString(table_to_text(t)))
    body = None
    for sel in ["#article", "div.col-xs-12.col-sm-8", "#content", "#leftText", "body"]:
        body = soup.select_one(sel)
        if body:
            break
    text = (body or soup).get_text(separator="\n")
    # Collapse whitespace but keep table rows on their own lines
    lines = [re.sub(r"[ \t]+", " ", ln).strip() for ln in text.splitlines()]
    out, blank = [], 0
    for ln in lines:
        if ln:
            out.append(ln)
            blank = 0
        else:
            blank += 1
            if blank == 1:
                out.append("")
    return "\n".join(out).strip()


def save_text(path, url, text, extra_header=""):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(f"SOURCE: {url}\n{extra_header}\n{text}\n", encoding="utf-8")


def save_pdf(path, url):
    if path.exists():
        return True
    data = fetch(url, binary=True)
    if not data or len(data) < 5000:
        return False
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data)
    return True


def pdf_to_text(path):
    if pdf_extract is None:
        return None
    try:
        return (pdf_extract(io.BytesIO(path.read_bytes())) or "").strip()
    except Exception as e:
        log.warning(f"PDF extract failed {path.name}: {e}")
        return None


# ── Per-meeting collector ──────────────────────────────────────────────────────
def collect(d, want_pdf=True):
    ok = {}

    # Layer 1a: projection materials, accessible HTML (2012 →)
    p = TXT_DIR / f"{d}_SEP_projections.txt"
    if d >= FIRST_PROJTABL_HTM:
        if p.exists():
            ok["proj_htm"] = "exists"
        else:
            url = f"{FED}/monetarypolicy/fomcprojtabl{d}.htm"
            html = fetch(url)
            time.sleep(DELAY)
            if not html:  # March 2022 was published under a misspelled slug
                url = f"{FED}/monetarypolicy/fomcprojtable{d}.htm"
                html = fetch(url)
                time.sleep(DELAY)
            if html and "fomcprojtabl" in html and "Page not found" not in html:
                save_text(p, url, html_to_text(html), "TYPE: I (SEP / dot plot) — projection materials, accessible version\n")
                ok["proj_htm"] = "saved"
            else:
                ok["proj_htm"] = "MISSING"
    # Layer 1b: projection materials PDF (2011 →), the original with the dot-plot figure
    if want_pdf and d >= FIRST_PROJTABL_PDF:
        url = f"{FED}/monetarypolicy/files/fomcprojtabl{d}.pdf"
        got = save_pdf(PDF_DIR / f"fomcprojtabl{d}.pdf", url)
        ok["proj_pdf"] = "ok" if got else "MISSING"
        time.sleep(DELAY)
        # 2011 has no HTML page: extract the PDF text so a committed text copy exists
        if d < FIRST_PROJTABL_HTM and got and not p.exists():
            txt = pdf_to_text(PDF_DIR / f"fomcprojtabl{d}.pdf")
            if txt:
                save_text(p, url, txt, "TYPE: I (SEP / dot plot) — projection materials, text extracted from PDF\n")
                ok["proj_htm"] = "saved(pdf-text)"

    # Layer 2: SEP addendum to the minutes (2007 →)
    p2 = TXT_DIR / f"{d}_SEP_minutes_addendum.txt"
    if d > LAST_EP_ADDENDUM:
        ok["addendum"] = "in-minutes"
    elif p2.exists():
        ok["addendum"] = "exists"
    else:
        url = f"{FED}/monetarypolicy/fomcminutes{d}ep.htm"
        html = fetch(url)
        time.sleep(DELAY)
        if html and ("Summary of Economic Projections" in html or "Economic Projections" in html):
            save_text(p2, url, html_to_text(html), "TYPE: I (SEP) — Summary of Economic Projections addendum to the minutes\n")
            ok["addendum"] = "saved"
        else:
            ok["addendum"] = "MISSING"

    # Layer 2b: accessible-figures companion page (fomcminutes{d}epa.htm). In
    # 2007–2014 the addendum's figure data (incl. the dot-plot histogram) lives
    # on this separate page; later it is inline in the addendum itself.
    p3 = TXT_DIR / f"{d}_SEP_minutes_addendum_figures.txt"
    if d > LAST_EP_ADDENDUM:
        pass
    elif p3.exists():
        ok["figures"] = "exists"
    else:
        url = f"{FED}/monetarypolicy/fomcminutes{d}epa.htm"
        html = fetch(url)
        time.sleep(DELAY)
        if html and "Page not Found" not in html and "Page not found" not in html:
            save_text(p3, url, html_to_text(html), "TYPE: I (SEP) — accessible figure data for the SEP addendum to the minutes\n")
            ok["figures"] = "saved"
        else:
            ok["figures"] = "none"

    # Layer 3: individual projections + participant key (2007–2020, 5-year lag)
    if want_pdf and d <= LAST_COMPILATION:
        comp = IND_DIR / f"FOMC{d}SEPcompilation.pdf"
        got = save_pdf(comp, f"{FED}/monetarypolicy/files/FOMC{d}SEPcompilation.pdf")
        ok["individual"] = "ok" if got else "MISSING"
        time.sleep(DELAY)
        if got:
            txt_path = comp.with_suffix(".txt")
            if not txt_path.exists():
                txt = pdf_to_text(comp)
                if txt:
                    save_text(txt_path, f"{FED}/monetarypolicy/files/FOMC{d}SEPcompilation.pdf", txt)
        key = IND_DIR / f"FOMC{d}SEPkey.pdf"
        gotk = save_pdf(key, f"{FED}/monetarypolicy/files/FOMC{d}SEPkey.pdf")
        ok["key"] = "ok" if gotk else "MISSING"
        time.sleep(DELAY)

    log.info(f"{d}: " + ", ".join(f"{k}={v}" for k, v in ok.items()))
    return ok


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dates", help="comma-separated YYYYMMDD list (default: discover all)")
    ap.add_argument("--no-pdf", action="store_true", help="skip PDF downloads (text only)")
    args = ap.parse_args()

    dates = args.dates.split(",") if args.dates else discover_dates()
    log.info(f"{len(dates)} projection meetings: {dates[0]} → {dates[-1]}")

    summary = {}
    for d in dates:
        summary[d] = collect(d, want_pdf=not args.no_pdf)

    missing = {d: [k for k, v in r.items() if v == "MISSING"] for d, r in summary.items()}
    missing = {d: m for d, m in missing.items() if m}
    log.info("── DONE ──")
    if missing:
        log.warning("Missing items:")
        for d, m in missing.items():
            log.warning(f"  {d}: {', '.join(m)}")
    else:
        log.info("Nothing missing.")


if __name__ == "__main__":
    main()
