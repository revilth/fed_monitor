import os
from pathlib import Path
from dotenv import load_dotenv

load_dotenv()

BASE_DIR = Path(__file__).parent
# data/ lives inside the project folder, which is already synced to Google Drive
# by the desktop client — no Drive API needed.
DATA_DIR = BASE_DIR / "data"

# Email
EMAIL_FROM = os.getenv("EMAIL_FROM", "")
EMAIL_TO = os.getenv("EMAIL_TO", "")
GMAIL_APP_PASSWORD = os.getenv("GMAIL_APP_PASSWORD", "")

# Storage — fully local; Drive sync is handled by the desktop app
LOCAL_RAW = DATA_DIR / "raw"
LOCAL_SCORED = DATA_DIR / "scored"
LOCAL_REPORTS = DATA_DIR / "reports"

# Speaker tiers
TIER_1_SPEAKERS = {
    "Jerome Powell": "Chair",
    "Philip Jefferson": "Vice Chair",
    "John Williams": "NY Fed President",
}

# 2026 FOMC voters (update annually from https://www.federalreserve.gov/monetarypolicy/fomc.htm)
TIER_2_VOTERS = {
    "Jerome Powell",
    "Philip Jefferson",
    "John Williams",
    "Michael Barr",
    "Michelle Bowman",
    "Lisa Cook",
    "Austan Goolsbee",     # Chicago
    "Anna Paulson",        # Philadelphia (new president 2026; replaced Harker)
    "Susan Collins",       # Boston (rotating)
    "Alberto Musalem",     # St. Louis (rotating)
    "Adriana Kugler",
    "Christopher Waller",
    "Stephen Miran",       # New Board Governor 2026
}

# Current cycle regime (analyst updates this)
CYCLE_REGIME = os.getenv("CYCLE_REGIME", "holding")  # tightening / holding / easing

# Scraping
SPEECH_START_DATE = "2026-01-01"
REQUEST_DELAY_SECONDS = 2.0
MAX_RETRIES = 3
REQUEST_TIMEOUT = 30

# Fed Board sources
FED_BOARD_SPEECHES_URL = "https://www.federalreserve.gov/newsevents/speeches.htm"
FED_BOARD_TESTIMONY_URL = "https://www.federalreserve.gov/newsevents/testimony.htm"
FED_BOARD_FOMC_URL = "https://www.federalreserve.gov/monetarypolicy/fomccalendars.htm"

# Regional Fed speech URLs
REGIONAL_FED_URLS = {
    "Boston": "https://www.bostonfed.org/news-and-events/speeches.aspx",
    "New York": "https://www.newyorkfed.org/newsevents/speeches",
    "Philadelphia": "https://www.philadelphiafed.org/the-economy/speeches-anna-paulson",
    "Cleveland": "https://www.clevelandfed.org/collections/speeches",
    "Richmond": "https://www.richmondfed.org/press_room/speeches",
    "Atlanta": "https://www.atlantafed.org/news-and-events/speeches",
    "Chicago": "https://www.chicagofed.org/utilities/about-us/office-of-the-president/office-of-the-president-speaking",
    "St. Louis": "https://www.stlouisfed.org/from-the-president/remarks",
    "Minneapolis": "https://www.minneapolisfed.org/speeches",
    "Kansas City": "https://www.kansascityfed.org/speeches",
    "Dallas": "https://www.dallasfed.org/news/speeches",
    "San Francisco": "https://www.frbsf.org/our-district/press/presidents-speeches",
}

# YouTube channels for transcript extraction
YOUTUBE_CHANNELS = {
    "Federal Reserve": "https://www.youtube.com/@FederalReserve",
    "Brookings": "https://www.youtube.com/@BrookingsInstitution",
    "CFR": "https://www.youtube.com/@CFR_org",
    "PIIE": "https://www.youtube.com/@PIIE_org",
}
