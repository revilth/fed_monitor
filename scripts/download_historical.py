#!/usr/bin/env python3
"""
Historical Fed communications downloader.

Phases:
  1. BIS — download full text corpus ZIP (1997-present, all central banks)
  2. FRASER harvest — OAI-PMH metadata → JSON manifests
  3. FRASER extract — Playwright fulltext from item pages (resumable, 10 s crawl delay)

Usage:
  python3 scripts/download_historical.py            # all three phases
  python3 scripts/download_historical.py --phase 1  # BIS only
  python3 scripts/download_historical.py --phase 2  # OAI harvest only
  python3 scripts/download_historical.py --phase 3  # Playwright extract only

Progress log : data/historical/download.log
Error log    : data/historical/download_errors.log
"""

import argparse
import asyncio
import json
import logging
import re
import ssl
import subprocess
import sys
import time
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from pathlib import Path

import certifi
SSL_CTX = ssl.create_default_context(cafile=certifi.where())

# ── directories ────────────────────────────────────────────────────────────────
BASE_DIR    = Path(__file__).resolve().parent.parent
DATA_DIR    = BASE_DIR / 'data' / 'historical'
BIS_DIR     = DATA_DIR / 'raw' / 'bis'
FRASER_DIR  = DATA_DIR / 'raw' / 'fraser'
FOMC_DIR    = DATA_DIR / 'raw' / 'fomc'        # Fed Board FOMC minutes + transcripts
MANIFEST_DIR = DATA_DIR / 'manifests'
LOG_FILE    = DATA_DIR / 'download.log'
ERROR_FILE  = DATA_DIR / 'download_errors.log'

FRASER_OAI  = 'https://fraser.stlouisfed.org/oai'
CRAWL_DELAY = 10  # seconds — per robots.txt

# ── Fed Board FOMC historical ──────────────────────────────────────────────────
# FRASER's author:10 OAI set times out (returns 0 bytes). The Fed Board website
# hosts every FOMC minutes/transcript/policy-record document directly as PDF/HTML.
FEDBOARD_BASE      = 'https://www.federalreserve.gov'
FEDBOARD_FOMC_HIST = f'{FEDBOARD_BASE}/monetarypolicy/fomc_historical_year.htm'
FEDBOARD_DELAY     = 2  # seconds between requests — federalreserve.gov is robust
# Year range to scan (transcripts have a 5-year release lag; index runs 1936-present)
FEDBOARD_YEAR_MIN  = 1936
FEDBOARD_YEAR_MAX  = 2020

# ── FRASER targets ─────────────────────────────────────────────────────────────
# Each entry: set_id (OAI set), subdir (under FRASER_DIR/), optional filters.
FRASER_TARGETS = {
    'volcker': {
        'set_id':        'author:23',
        'subdir':        'speeches/volcker',
        'year_max':      None,
        'title_filter':  None,
        'genre_filter':  {'speech', 'testimony', 'remarks', 'interview'},
        'description':   'Paul Volcker — speeches/testimony only',
    },
    'greenspan': {
        'set_id':        'author:21',
        'subdir':        'speeches/greenspan',
        'year_max':      1996,
        'title_filter':  None,
        'genre_filter':  {'speech', 'testimony', 'remarks', 'interview'},
        'description':   'Alan Greenspan — pre-1997 speeches/testimony only',
    },
    'corrigan': {
        'set_id':        'author:2595',
        'subdir':        'speeches/corrigan',
        'year_max':      None,
        'title_filter':  None,
        'genre_filter':  None,   # all 19 records are relevant
        'description':   'E. Gerald Corrigan — NY Fed president 1985-1993',
    },
    'mcdonough': {
        'set_id':        'author:3085',
        'subdir':        'speeches/mcdonough',
        'year_max':      1996,
        'title_filter':  None,
        'genre_filter':  None,   # all 28 records are speeches
        'description':   'William J. McDonough — NY Fed 1993-2003, pre-1997 only',
    },
    'fomc': {
        'set_id':        'author:10',
        'subdir':        'fomc',
        'year_max':      None,
        'title_filter':  ['minutes', 'transcript', 'transcripts'],
        'genre_filter':  None,
        'description':   'FOMC minutes + transcripts — harvested in year-range chunks',
        'chunk_years':   True,   # special: harvest via 5-year date-range chunks
    },
}


# ── logging setup (called after dirs exist) ───────────────────────────────────
def setup_logging():
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s [%(levelname)s] %(message)s',
        handlers=[
            logging.FileHandler(LOG_FILE),
            logging.StreamHandler(sys.stdout),
        ],
    )


log = logging.getLogger(__name__)


def setup_dirs():
    for key, cfg in FRASER_TARGETS.items():
        (FRASER_DIR / cfg['subdir']).mkdir(parents=True, exist_ok=True)
    BIS_DIR.mkdir(parents=True, exist_ok=True)
    MANIFEST_DIR.mkdir(parents=True, exist_ok=True)
    for sub in ('transcripts', 'minutes', 'policy_records'):
        (FOMC_DIR / sub).mkdir(parents=True, exist_ok=True)


# ── helpers ────────────────────────────────────────────────────────────────────
def safe_filename(title: str, date: str, oai_id: str) -> str:
    date_tag = re.sub(r'[^0-9]', '', (date or '')[:10])[:8].ljust(8, '0')
    slug = re.sub(r'[^\w\s-]', '', (title or '').lower())
    slug = re.sub(r'\s+', '_', slug.strip())[:50]
    # OAI IDs look like "oai:fraser.stlouisfed.org:item:801" — extract trailing number
    m = re.search(r'(\d+)$', oai_id or '')
    item_id = m.group(1) if m else 'unknown'
    return f"{date_tag}_{slug}_{item_id}.txt"


def item_to_fulltext_url(item_url: str) -> str:
    u = item_url.rstrip('/')
    return u if u.endswith('/fulltext') else u + '/fulltext'


# ── Phase 1: BIS corpus ────────────────────────────────────────────────────────
def phase1_bis() -> bool:
    log.info('=== PHASE 1: BIS corpus download ===')
    bis_zip = BIS_DIR / 'bis_speeches_corpus.zip'

    if bis_zip.exists() and bis_zip.stat().st_size > 50_000_000:
        log.info(f'BIS ZIP already present ({bis_zip.stat().st_size:,} bytes) — skipping download.')
    else:
        log.info('Fetching BIS download page to locate ZIP URL...')
        r = subprocess.run(
            ['curl', '--http1.1', '-s', '-L',
             'https://www.bis.org/cbspeeches/download.htm'],
            capture_output=True, text=True, timeout=30,
        )
        html = r.stdout

        zip_links = re.findall(r'href="([^"]+\.zip)"', html, re.IGNORECASE)
        if not zip_links:
            zip_links = re.findall(r'"(https?://[^"]+\.zip)"', html)

        if zip_links:
            # Prefer full corpus ZIP (speeches.zip) over year-specific ones (speeches_2025.zip)
            full_corpus = [z for z in zip_links if re.search(r'/speeches\.zip$', z)]
            zip_url = full_corpus[0] if full_corpus else zip_links[0]
            if not zip_url.startswith('http'):
                zip_url = 'https://www.bis.org' + zip_url
            log.info(f'Found BIS ZIP URL: {zip_url}')
        else:
            zip_url = 'https://www.bis.org/speeches/speeches.zip'
            log.info(f'No ZIP link found in page HTML; trying known URL: {zip_url}')

        log.info(f'Downloading BIS corpus ZIP (may take several minutes)...')
        r = subprocess.run(
            ['curl', '--http1.1', '-L', '-o', str(bis_zip), zip_url],
            timeout=900,
        )
        if r.returncode != 0 or not bis_zip.exists():
            log.error(f'BIS download failed (exit {r.returncode}). '
                      'Manual download may be needed from https://www.bis.org/cbspeeches/download.htm')
            return False
        log.info(f'BIS ZIP saved: {bis_zip.stat().st_size:,} bytes')

    # Extract — use a marker file to avoid re-extracting on resume
    marker = BIS_DIR / 'CORPUS_EXTRACTED'
    if marker.exists():
        log.info('BIS corpus already extracted (marker present) — skipping unzip.')
    else:
        log.info('Extracting BIS ZIP...')
        r = subprocess.run(
            ['unzip', '-o', str(bis_zip), '-d', str(BIS_DIR)],
            capture_output=True, text=True, timeout=600,
        )
        if r.returncode != 0:
            log.error(f'Unzip failed: {r.stderr[:500]}')
        else:
            csv_files = list(BIS_DIR.glob('*.csv'))
            log.info(f'BIS ZIP extracted to {BIS_DIR}. CSV files: {[f.name for f in csv_files]}')
            marker.write_text('extracted')  # leave marker so we never re-extract

    log.info('Phase 1 complete.')
    return True


# ── Phase 2: FRASER OAI-PMH harvest ───────────────────────────────────────────
def harvest_oai_set(key: str, cfg: dict) -> list:
    set_id       = cfg['set_id']
    year_max     = cfg.get('year_max')
    title_filter = cfg.get('title_filter')
    records      = []
    token        = None
    page_num     = 0

    while True:
        page_num += 1
        if token:
            url = (f"{FRASER_OAI}?verb=ListRecords"
                   f"&resumptionToken={urllib.parse.quote(token)}")
        else:
            # FRASER always returns MODS regardless of metadataPrefix; request mods explicitly
            url = (f"{FRASER_OAI}?verb=ListRecords"
                   f"&set={urllib.parse.quote(set_id)}"
                   f"&metadataPrefix=mods")

        log.info(f'[{key}] OAI page {page_num}: {url[:100]}')
        try:
            # Use curl --http1.1 — FRASER's server has HTTP/2 stream reset issues
            r = subprocess.run(
                ['curl', '--http1.1', '-s', '-L', '--max-time', '60',
                 '-H', 'User-Agent: FedMonitor/1.0 (research; revilth@gmail.com)',
                 url],
                capture_output=True, text=True, timeout=70,
            )
            if r.returncode != 0:
                raise RuntimeError(f'curl exit {r.returncode}: {r.stderr[:200]}')
            raw = r.stdout
            if not raw.strip():
                raise RuntimeError('Empty response from FRASER OAI')
        except Exception as e:
            log.error(f'[{key}] OAI request failed: {e}; retrying in 10s...')
            time.sleep(10)
            continue

        try:
            root = ET.fromstring(raw)
        except ET.ParseError as e:
            log.error(f'[{key}] XML parse error on page {page_num}: {e}')
            log.debug(raw[:300])
            break

        ns = {
            'oai':  'http://www.openarchives.org/OAI/2.0/',
            'mods': 'http://www.loc.gov/mods/v3',
        }

        for rec in root.findall('.//oai:record', ns):
            hdr = rec.find('oai:header', ns)
            if hdr is not None and hdr.get('status') == 'deleted':
                continue

            meta = rec.find('.//oai:metadata', ns)
            if meta is None:
                continue

            mods_el = meta.find('mods:mods', ns)
            if mods_el is None:
                continue

            # Title
            title_el    = mods_el.find('mods:titleInfo/mods:title', ns)
            subtitle_el = mods_el.find('mods:titleInfo/mods:subTitle', ns)
            title    = (title_el.text or '').strip()    if title_el    is not None else ''
            subtitle = (subtitle_el.text or '').strip() if subtitle_el is not None else ''

            # Date — sortDate is ISO (YYYY-MM-DD); fall back to dateIssued
            date_el  = mods_el.find('mods:originInfo/mods:sortDate', ns)
            date_str = (date_el.text or '').strip() if date_el is not None else ''
            if not date_str:
                di_el    = mods_el.find('mods:originInfo/mods:dateIssued', ns)
                date_str = (di_el.text or '').strip() if di_el is not None else ''

            # URL — mods:location/mods:url is the item page
            url_el   = mods_el.find('mods:location/mods:url', ns)
            item_url = (url_el.text or '').strip() if url_el is not None else ''

            # Genre (used for FOMC filtering)
            genre_el = mods_el.find('mods:genre', ns)
            genre    = (genre_el.text or '').lower().strip() if genre_el is not None else ''

            # Year filter
            year = None
            m = re.match(r'(\d{4})', date_str)
            if m:
                year = int(m.group(1))
            if year_max and year and year > year_max:
                continue

            # Keyword filter — check title + subtitle + genre combined
            if title_filter:
                combined = f"{title.lower()} {subtitle.lower()} {genre}"
                if not any(kw in combined for kw in title_filter):
                    continue

            oai_id_el = hdr.find('oai:identifier', ns) if hdr is not None else None
            oai_id    = (oai_id_el.text or '').strip() if oai_id_el is not None else ''

            records.append({
                'key':      key,
                'subdir':   cfg['subdir'],
                'title':    title,
                'subtitle': subtitle,
                'date':     date_str,
                'year':     year,
                'url':      item_url,
                'genre':    genre,
                'oai_id':   oai_id,
            })

        # Pagination
        rt = root.find('.//oai:resumptionToken', ns)
        if rt is not None and rt.text and rt.text.strip():
            token = rt.text.strip()
        else:
            break

        time.sleep(1)  # polite pause between OAI pages

    log.info(f'[{key}] Harvest complete — {len(records)} qualifying records.')
    return records


def harvest_fomc_chunked(key: str, cfg: dict) -> list:
    """Harvest FOMC set in 5-year chunks to avoid OAI pagination failures."""
    all_records: list[dict] = []
    # FOMC minutes go back to ~1936; transcripts to 1993. Use 5-year windows.
    for decade_start in range(1935, 2026, 5):
        from_date  = f'{decade_start}-01-01'
        until_date = f'{min(decade_start + 4, 2025)}-12-31'
        chunk_url  = (f"{FRASER_OAI}?verb=ListRecords"
                      f"&set={urllib.parse.quote(cfg['set_id'])}"
                      f"&metadataPrefix=mods"
                      f"&from={from_date}&until={until_date}")

        token   = None
        page_num = 0
        chunk_records: list[dict] = []

        while True:
            page_num += 1
            url = (f"{FRASER_OAI}?verb=ListRecords"
                   f"&resumptionToken={urllib.parse.quote(token)}") if token else chunk_url

            log.info(f'[{key}] {from_date[:4]}-{until_date[:4]} page {page_num}: {url[:100]}')
            try:
                r = subprocess.run(
                    ['curl', '--http1.1', '-s', '-L', '--max-time', '60',
                     '-H', 'User-Agent: FedMonitor/1.0 (research; revilth@gmail.com)',
                     url],
                    capture_output=True, text=True, timeout=70,
                )
                if r.returncode != 0:
                    raise RuntimeError(f'curl exit {r.returncode}: {r.stderr[:200]}')
                raw = r.stdout
                if not raw.strip():
                    log.warning(f'[{key}] Empty response for {from_date[:4]}-{until_date[:4]} '
                                f'page {page_num} — skipping chunk remainder.')
                    break
            except Exception as e:
                log.error(f'[{key}] Request failed: {e}; skipping.')
                break

            try:
                root = ET.fromstring(raw)
            except ET.ParseError as e:
                log.error(f'[{key}] XML parse error: {e}')
                break

            ns = {
                'oai':  'http://www.openarchives.org/OAI/2.0/',
                'mods': 'http://www.loc.gov/mods/v3',
            }

            # Check for OAI error (e.g., noRecordsMatch)
            err_el = root.find('.//oai:error', ns)
            if err_el is not None:
                log.info(f'[{key}] OAI error for {from_date[:4]}-{until_date[:4]}: '
                         f'{err_el.get("code")} — {err_el.text}')
                break

            for rec in root.findall('.//oai:record', ns):
                hdr = rec.find('oai:header', ns)
                if hdr is not None and hdr.get('status') == 'deleted':
                    continue
                meta = rec.find('.//oai:metadata', ns)
                if meta is None:
                    continue
                mods_el = meta.find('mods:mods', ns)
                if mods_el is None:
                    continue

                title_el    = mods_el.find('mods:titleInfo/mods:title', ns)
                subtitle_el = mods_el.find('mods:titleInfo/mods:subTitle', ns)
                date_el     = mods_el.find('mods:originInfo/mods:sortDate', ns)
                url_el      = mods_el.find('mods:location/mods:url', ns)
                genre_el    = mods_el.find('mods:genre', ns)
                oai_id_el   = hdr.find('oai:identifier', ns) if hdr is not None else None

                title    = (title_el.text    or '').strip() if title_el    is not None else ''
                subtitle = (subtitle_el.text or '').strip() if subtitle_el is not None else ''
                date_str = (date_el.text     or '').strip() if date_el     is not None else ''
                item_url = (url_el.text      or '').strip() if url_el      is not None else ''
                genre    = (genre_el.text    or '').lower().strip() if genre_el is not None else ''
                oai_id   = (oai_id_el.text   or '').strip() if oai_id_el   is not None else ''

                year = None
                m = re.match(r'(\d{4})', date_str)
                if m:
                    year = int(m.group(1))

                # Title keyword filter
                title_filter = cfg.get('title_filter')
                if title_filter:
                    combined = f"{title.lower()} {subtitle.lower()} {genre}"
                    if not any(kw in combined for kw in title_filter):
                        continue

                chunk_records.append({
                    'key': key, 'subdir': cfg['subdir'],
                    'title': title, 'subtitle': subtitle,
                    'date': date_str, 'year': year,
                    'url': item_url, 'genre': genre, 'oai_id': oai_id,
                })

            rt = root.find('.//oai:resumptionToken', ns)
            if rt is not None and rt.text and rt.text.strip():
                token = rt.text.strip()
            else:
                break

            time.sleep(1)

        log.info(f'[{key}] {from_date[:4]}-{until_date[:4]}: {len(chunk_records)} records')
        all_records.extend(chunk_records)
        time.sleep(2)  # pause between chunks

    log.info(f'[{key}] Total across all chunks: {len(all_records)} records')
    return all_records


def phase2_harvest() -> bool:
    log.info('=== PHASE 2: FRASER OAI-PMH harvest ===')

    total = 0
    for key, cfg in FRASER_TARGETS.items():
        manifest_path = MANIFEST_DIR / f'fraser_{key}.json'
        if manifest_path.exists():
            existing = json.loads(manifest_path.read_text())
            log.info(f'[{key}] Manifest exists ({len(existing)} records) — skipping harvest.')
            total += len(existing)
            continue

        if cfg.get('chunk_years'):
            records = harvest_fomc_chunked(key, cfg)
        else:
            records = harvest_oai_set(key, cfg)

        manifest_path.write_text(json.dumps(records, indent=2, ensure_ascii=False))
        log.info(f'[{key}] Manifest saved: {manifest_path}')
        total += len(records)

    # Write human-readable summary
    lines = ['FRASER manifest summary', '=' * 40]
    for key in FRASER_TARGETS:
        mp = MANIFEST_DIR / f'fraser_{key}.json'
        n = len(json.loads(mp.read_text())) if mp.exists() else 0
        lines.append(f'  {key:15s}: {n:5d} records  — {FRASER_TARGETS[key]["description"]}')
    lines.append(f'\n  TOTAL: {total}')
    summary_text = '\n'.join(lines)
    (MANIFEST_DIR / 'summary.txt').write_text(summary_text + '\n')
    log.info('Phase 2 complete.\n' + summary_text)
    return True


# ── Phase 3: Playwright fulltext extraction ────────────────────────────────────
async def extract_one(page, url: str, out_path: Path, label: str) -> bool:
    fulltext_url = item_to_fulltext_url(url)
    try:
        await page.goto(fulltext_url, wait_until='domcontentloaded', timeout=30_000)
        await asyncio.sleep(3)

        content = ''
        for sel in [
            '#fulltext-container',
            '.item-fulltext',
            '.speech-content',
            'article .content',
            'main article',
            'article',
            'main',
            '.container',
        ]:
            try:
                el = await page.query_selector(sel)
                if el:
                    text = await el.inner_text()
                    if len(text) > 300:
                        content = text
                        break
            except Exception:
                pass

        if not content:
            body = await page.query_selector('body')
            if body:
                content = await body.inner_text()

        if not content or len(content) < 100:
            log.warning(f'[{label}] Short content ({len(content)} chars): {fulltext_url}')
            return False

        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text(f'SOURCE: {fulltext_url}\n\n{content}', encoding='utf-8')
        log.info(f'[{label}] Saved {out_path.name} ({len(content):,} chars)')
        return True

    except Exception as e:
        log.error(f'[{label}] Playwright error {fulltext_url}: {e}')
        return False


async def phase3_playwright_async() -> bool:
    log.info('=== PHASE 3: FRASER fulltext extraction via Playwright ===')

    # Load all manifests
    all_items: list[dict] = []
    for key in FRASER_TARGETS:
        mp = MANIFEST_DIR / f'fraser_{key}.json'
        if not mp.exists():
            log.warning(f'[{key}] No manifest found — run phase 2 first.')
            continue
        items = json.loads(mp.read_text())
        all_items.extend(items)

    log.info(f'Total items across all manifests: {len(all_items)}')

    # Build pending list (skip already-saved and genre-filtered-out items)
    pending: list[tuple[dict, Path]] = []
    for item in all_items:
        if not item.get('url'):
            continue
        # Apply genre filter from FRASER_TARGETS config
        cfg_key = item.get('key', '')
        genre_filter = FRASER_TARGETS.get(cfg_key, {}).get('genre_filter')
        if genre_filter and item.get('genre', '') not in genre_filter:
            continue
        out_dir  = FRASER_DIR / item['subdir']
        fname    = safe_filename(item['title'], item['date'], item['oai_id'])
        out_path = out_dir / fname
        if out_path.exists() and out_path.stat().st_size > 100:
            continue
        pending.append((item, out_path))

    already_done = len(all_items) - len(pending)
    log.info(f'Already saved: {already_done} | Pending: {len(pending)}')
    if not pending:
        log.info('Nothing to download. Phase 3 complete.')
        return True

    est_hrs = len(pending) * (CRAWL_DELAY + 5) / 3600
    log.info(f'Estimated time at {CRAWL_DELAY}s crawl delay: {est_hrs:.1f} hours')

    from playwright.async_api import async_playwright

    async with async_playwright() as pw:
        browser = await pw.chromium.launch(headless=True)
        ctx     = await browser.new_context(
            user_agent=(
                'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) '
                'AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36'
            )
        )
        page = await ctx.new_page()

        ok_count   = 0
        fail_count = 0

        for i, (item, out_path) in enumerate(pending, 1):
            log.info(
                f'[{i}/{len(pending)}] {item["key"]} | '
                f'{item["date"]} | {item["title"][:65]}'
            )
            success = await extract_one(page, item['url'], out_path, item['key'])
            if success:
                ok_count += 1
            else:
                fail_count += 1
                with open(ERROR_FILE, 'a') as ef:
                    ef.write(f'{item["url"]}\t{item["title"]}\t{item["date"]}\n')

            if i % 100 == 0:
                log.info(
                    f'--- Checkpoint {i}/{len(pending)} | '
                    f'ok={ok_count} fail={fail_count} ---'
                )

            if i < len(pending):
                await asyncio.sleep(CRAWL_DELAY)

        await browser.close()

    log.info(f'Phase 3 complete: ok={ok_count}  fail={fail_count}  total={len(pending)}')
    return True


def phase3_playwright():
    asyncio.run(phase3_playwright_async())


# ── Phase 4: Fed Board FOMC minutes + transcripts ─────────────────────────────
def _curl_text(url: str, timeout: int = 60) -> str:
    """Fetch a URL as text via curl. Decodes robustly — older federalreserve.gov
    minutes pages (2007-2011) are Windows-1252, not UTF-8."""
    r = subprocess.run(
        ['curl', '-s', '-L', '--max-time', str(timeout),
         '-H', 'User-Agent: FedMonitor/1.0 (research; revilth@gmail.com)', url],
        capture_output=True, timeout=timeout + 10,   # bytes, not text
    )
    if r.returncode != 0:
        return ''
    raw = r.stdout
    for enc in ('utf-8', 'cp1252', 'latin-1'):
        try:
            return raw.decode(enc)
        except UnicodeDecodeError:
            continue
    return raw.decode('utf-8', errors='replace')


def _curl_binary(url: str, out_path: Path, timeout: int = 120) -> bool:
    """Download a binary file (PDF) via curl."""
    r = subprocess.run(
        ['curl', '-s', '-L', '--max-time', str(timeout), '-o', str(out_path),
         '-H', 'User-Agent: FedMonitor/1.0 (research; revilth@gmail.com)', url],
        timeout=timeout + 15,
    )
    return r.returncode == 0 and out_path.exists() and out_path.stat().st_size > 1000


def html_to_text(html: str) -> str:
    """Strip a federalreserve.gov minutes HTML page down to readable text."""
    # Drop scripts/styles, then tags, then collapse whitespace
    html = re.sub(r'<script[^>]*>.*?</script>', ' ', html, flags=re.S | re.I)
    html = re.sub(r'<style[^>]*>.*?</style>',  ' ', html, flags=re.S | re.I)
    # Prefer the main article container if present
    m = re.search(r'<div[^>]*id="article"[^>]*>(.*?)</div>\s*</div>', html, re.S | re.I)
    body = m.group(1) if m else html
    body = re.sub(r'<(p|br|div|li|h\d)[^>]*>', '\n', body, flags=re.I)
    text = re.sub(r'<[^>]+>', '', body)
    # HTML entities
    for ent, ch in (('&amp;', '&'), ('&nbsp;', ' '), ('&#39;', "'"),
                    ('&quot;', '"'), ('&ldquo;', '"'), ('&rdquo;', '"'),
                    ('&rsquo;', "'"), ('&lsquo;', "'"), ('&mdash;', '—'),
                    ('&ndash;', '–'), ('&lt;', '<'), ('&gt;', '>')):
        text = text.replace(ent, ch)
    text = re.sub(r'\n[ \t]+', '\n', text)
    text = re.sub(r'\n{3,}', '\n\n', text)
    return text.strip()


def phase4_fomc_manifest() -> list:
    """Build manifest of Fed Board FOMC minutes/transcripts/policy-record docs."""
    manifest_path = MANIFEST_DIR / 'fedboard_fomc.json'
    if manifest_path.exists():
        existing = json.loads(manifest_path.read_text())
        log.info(f'[fomc] Manifest exists ({len(existing)} docs) — skipping harvest.')
        return existing

    log.info(f'[fomc] Scanning Fed Board year pages '
             f'{FEDBOARD_YEAR_MIN}-{FEDBOARD_YEAR_MAX}...')
    docs: list[dict] = []
    seen: set = set()  # (date, doc_type) dedupe — prefer .htm over .pdf for minutes

    for year in range(FEDBOARD_YEAR_MIN, FEDBOARD_YEAR_MAX + 1):
        year_url = f'{FEDBOARD_BASE}/monetarypolicy/fomchistorical{year}.htm'
        html = _curl_text(year_url, timeout=30)
        if not html:
            log.warning(f'[fomc] {year}: empty page — skipping.')
            time.sleep(FEDBOARD_DELAY)
            continue

        links = re.findall(r'href="([^"]+\.(?:pdf|htm))"', html, re.I)
        year_count = 0
        for link in links:
            fn = link.split('/')[-1]
            fn_l = fn.lower()
            doc_type, date_tag = None, None

            # Transcript: FOMC{YYYYMMDD}meeting.pdf
            m = re.match(r'fomc(\d{8})meeting\.pdf$', fn_l)
            if m:
                doc_type, date_tag = 'transcript', m.group(1)

            # Minutes (modern .htm): fomcminutes{YYYYMMDD}.htm OR {YYYYMMDD}min.htm
            if not doc_type:
                m = (re.match(r'fomcminutes(\d{8})\.htm$', fn_l)
                     or re.match(r'(\d{8})min\.htm$', fn_l))
                if m:
                    doc_type, date_tag = 'minutes', m.group(1)

            # Minutes (pdf fallback)
            if not doc_type:
                m = re.match(r'fomcminutes(\d{8})\.pdf$', fn_l)
                if m:
                    doc_type, date_tag = 'minutes_pdf', m.group(1)

            # Record of Policy Actions / Minutes of Actions (pre-1993 equivalents)
            if not doc_type:
                m = re.match(r'fomc(?:ropa|moa)(\d{6,8})\.pdf$', fn_l)
                if m:
                    doc_type, date_tag = 'policy_record', m.group(1)

            if not doc_type:
                continue

            # Normalize date to 8 digits (pad 6-digit YYYYMM with 00)
            if len(date_tag) == 6:
                date_tag = date_tag + '00'

            full_url = link if link.startswith('http') else FEDBOARD_BASE + link

            # Dedupe: minutes .htm beats minutes_pdf for same date
            base_type = 'minutes' if doc_type in ('minutes', 'minutes_pdf') else doc_type
            key = (date_tag, base_type)
            if base_type == 'minutes':
                if key in seen and doc_type == 'minutes_pdf':
                    continue  # already have an htm version
                if key in seen and doc_type == 'minutes':
                    # replace any pdf entry with htm
                    docs[:] = [d for d in docs
                               if not (d['date'] == date_tag and d['doc_type'] in ('minutes', 'minutes_pdf'))]
            elif key in seen:
                continue
            seen.add(key)

            docs.append({
                'date':     date_tag,
                'year':     year,
                'doc_type': doc_type,
                'url':      full_url,
                'is_pdf':   fn_l.endswith('.pdf'),
            })
            year_count += 1

        log.info(f'[fomc] {year}: {year_count} target docs')
        time.sleep(FEDBOARD_DELAY)

    manifest_path.write_text(json.dumps(docs, indent=2))
    # Summary by type
    from collections import Counter
    by_type = Counter(d['doc_type'] for d in docs)
    log.info(f'[fomc] Manifest saved: {len(docs)} docs — {dict(by_type)}')
    return docs


def phase4_fomc_download() -> bool:
    log.info('=== PHASE 4: Fed Board FOMC minutes + transcripts ===')
    docs = phase4_fomc_manifest()
    if not docs:
        log.warning('[fomc] No documents in manifest.')
        return False

    # Map doc_type → output subdir
    subdir_map = {
        'transcript':    'transcripts',
        'minutes':       'minutes',
        'minutes_pdf':   'minutes',
        'policy_record': 'policy_records',
    }

    # Build pending list (skip already-saved .txt)
    pending = []
    for d in docs:
        sub  = subdir_map[d['doc_type']]
        tag  = 'transcript' if d['doc_type'] == 'transcript' else \
               'minutes' if d['doc_type'] in ('minutes', 'minutes_pdf') else 'policy_record'
        out  = FOMC_DIR / sub / f"{d['date']}_{tag}.txt"
        if out.exists() and out.stat().st_size > 200:
            continue
        pending.append((d, out))

    log.info(f'[fomc] Total docs: {len(docs)} | Already saved: '
             f'{len(docs) - len(pending)} | Pending: {len(pending)}')
    if not pending:
        log.info('[fomc] Nothing to download. Phase 4 complete.')
        return True

    ok = fail = 0
    tmp_pdf = FOMC_DIR / '_tmp_download.pdf'

    for i, (d, out) in enumerate(pending, 1):
        log.info(f'[fomc {i}/{len(pending)}] {d["date"]} {d["doc_type"]}: {d["url"].split("/")[-1]}')
        try:
            if d['is_pdf']:
                if _curl_binary(d['url'], tmp_pdf):
                    from pdfminer.high_level import extract_text
                    text = extract_text(str(tmp_pdf)) or ''
                    tmp_pdf.unlink(missing_ok=True)
                    if len(text) > 200:
                        out.write_text(f'SOURCE: {d["url"]}\n\n{text}', encoding='utf-8')
                        ok += 1
                        log.info(f'[fomc]   saved {out.name} ({len(text):,} chars)')
                    else:
                        fail += 1
                        log.warning(f'[fomc]   thin PDF text ({len(text)} chars): {d["url"]}')
                else:
                    fail += 1
                    log.warning(f'[fomc]   PDF download failed: {d["url"]}')
            else:
                html = _curl_text(d['url'], timeout=40)
                text = html_to_text(html)
                if len(text) > 200:
                    out.write_text(f'SOURCE: {d["url"]}\n\n{text}', encoding='utf-8')
                    ok += 1
                    log.info(f'[fomc]   saved {out.name} ({len(text):,} chars)')
                else:
                    fail += 1
                    log.warning(f'[fomc]   thin HTML text ({len(text)} chars): {d["url"]}')
        except Exception as e:
            fail += 1
            log.error(f'[fomc]   error {d["url"]}: {e}')
            with open(ERROR_FILE, 'a') as ef:
                ef.write(f'{d["url"]}\t{d["doc_type"]}\t{d["date"]}\n')

        if i % 50 == 0:
            log.info(f'--- [fomc] Checkpoint {i}/{len(pending)} | ok={ok} fail={fail} ---')

        if i < len(pending):
            time.sleep(FEDBOARD_DELAY)

    tmp_pdf.unlink(missing_ok=True)
    log.info(f'Phase 4 complete: ok={ok} fail={fail} total={len(pending)}')
    return True


# ── entry point ────────────────────────────────────────────────────────────────
def main():
    parser = argparse.ArgumentParser(
        description='Historical Fed communications downloader'
    )
    parser.add_argument(
        '--phase', type=int, choices=[1, 2, 3, 4],
        help='Run only this phase (default: all four in order). '
             '1=BIS 2=FRASER harvest 3=FRASER extract 4=Fed Board FOMC',
    )
    args = parser.parse_args()

    setup_logging()
    setup_dirs()

    log.info(f'=== Fed Historical Downloader starting ===')
    log.info(f'Data directory : {DATA_DIR}')
    log.info(f'Log file       : {LOG_FILE}')

    phases = [args.phase] if args.phase else [1, 2, 3, 4]

    if 1 in phases:
        phase1_bis()
    if 2 in phases:
        phase2_harvest()
    if 3 in phases:
        phase3_playwright()
    if 4 in phases:
        phase4_fomc_download()

    log.info('=== All requested phases complete ===')


if __name__ == '__main__':
    main()
