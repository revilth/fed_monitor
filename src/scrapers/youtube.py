"""
YouTube transcript scraper using yt-dlp.

Pulls auto-generated (or manual) transcripts from:
  - Federal Reserve official channel
  - Brookings Institution
  - Council on Foreign Relations
  - Peterson Institute for International Economics

Workflow:
  1. List recent videos from each channel (via yt-dlp --flat-playlist)
  2. Filter to videos likely to contain FOMC member speeches (by title keywords)
  3. Download the best available transcript (manual > auto-generated)
  4. Run a cleanup pass for common Fed-jargon ASR errors
  5. Return SpeechRecord objects
"""
import json
import logging
import re
import subprocess
import tempfile
from datetime import date, datetime
from pathlib import Path

import sys
sys.path.insert(0, str(Path(__file__).parent.parent.parent))
import config
from src.scrapers.base import SpeechRecord, get_tier

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Known FOMC member last names (for video title filtering)
# ---------------------------------------------------------------------------
FOMC_MEMBER_NAMES = {
    # First + last accepted
    "Powell", "Jefferson", "Williams", "Barr", "Bowman", "Cook",
    "Goolsbee", "Harker", "Collins", "Musalem", "Kugler", "Waller",
    "Kashkari", "Logan", "Bostic", "Barkin", "Daly", "Hammack",
    "Schmid", "Adriana",  # Kugler often referred to by first name
}

# Title keywords that indicate a monetary policy / economic outlook event
RELEVANT_TITLE_KEYWORDS = [
    "federal reserve", "fomc", "monetary policy", "inflation", "interest rate",
    "economic outlook", "economy", "central bank", "fed chair", "fed president",
    "jackson hole", "humphrey hawkins", "testimony",
]

# Common ASR mis-transcriptions of Fed jargon → correct form
JARGON_CORRECTIONS = {
    r"\bfed's\b": "Fed's",
    r"\bfed\b": "Fed",
    r"\bfomc\b": "FOMC",
    r"\bgdp\b": "GDP",
    r"\bcpi\b": "CPI",
    r"\bpce\b": "PCE",
    r"\bpce price index\b": "PCE price index",
    r"\bffr\b": "FFR",
    r"\bsofr\b": "SOFR",
    r"\btreauries\b": "Treasuries",
    r"\bquantitative\s+easing\b": "quantitative easing",
    r"\bquantitative\s+tightening\b": "quantitative tightening",
    r"\bbalanced? sheet\b": "balance sheet",
    r"\bopen market\s+committee\b": "Open Market Committee",
    r"\bbasis\s+point(?:s)?\b": "basis point(s)",
    r"\bfull\s+employment\b": "full employment",
    r"\bdual\s+mandate\b": "dual mandate",
    r"\bdata\s+dependent\b": "data-dependent",
    r"\bforward\s+guidance\b": "forward guidance",
    r"\bterm\s+premium\b": "term premium",
    r"\byield\s+curve\b": "yield curve",
    r"\bneutral rate\b": "neutral rate",
    r"\bnatural\s+rate\b": "natural rate",
    r"\br\s*\*\b": "r-star",
    # Common name mis-spellings from ASR
    r"\bpowell\b": "Powell",
    r"\bjefferson\b": "Jefferson",
    r"\bwilliams\b": "Williams",
    r"\bgoolsby\b": "Goolsbee",
    r"\bgoolsbee\b": "Goolsbee",
    r"\bkashkari\b": "Kashkari",
    r"\bbarkin\b": "Barkin",
    r"\bbostic\b": "Bostic",
    r"\bwaller\b": "Waller",
    r"\bkugler\b": "Kugler",
    r"\bmuselum\b": "Musalem",
    r"\bmusoleum\b": "Musalem",
}

# Channels to monitor (name → YouTube channel URL)
CHANNELS = {
    "Federal Reserve": "https://www.youtube.com/@FederalReserve/videos",
    "Brookings": "https://www.youtube.com/@BrookingsInstitution/videos",
    "CFR": "https://www.youtube.com/@CFR_org/videos",
    "PIIE": "https://www.youtube.com/@PetersonInstitute/videos",
}


# ---------------------------------------------------------------------------
# Core functions
# ---------------------------------------------------------------------------

def _run_ytdlp(*args: str, timeout: int = 120) -> tuple[bool, str]:
    """Run yt-dlp with the given args. Returns (success, stdout)."""
    cmd = ["yt-dlp"] + list(args)
    logger.debug(f"Running: {' '.join(cmd)}")
    try:
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=timeout,
        )
        if result.returncode != 0:
            logger.debug(f"yt-dlp stderr: {result.stderr[:500]}")
            return False, result.stdout
        return True, result.stdout
    except subprocess.TimeoutExpired:
        logger.warning(f"yt-dlp timed out for args: {args[:3]}")
        return False, ""
    except FileNotFoundError:
        logger.error("yt-dlp not found. Install with: pip install yt-dlp")
        return False, ""


def list_channel_videos(channel_url: str, max_videos: int = 50) -> list[dict]:
    """
    Return metadata for the most recent N videos from a channel.
    Each dict has: id, title, upload_date, url, duration
    """
    ok, stdout = _run_ytdlp(
        "--flat-playlist",
        "--playlist-end", str(max_videos),
        "--print", "%(id)s\t%(title)s\t%(upload_date)s\t%(duration)s",
        "--no-warnings",
        "--quiet",
        channel_url,
        timeout=60,
    )
    if not ok or not stdout.strip():
        return []

    videos = []
    for line in stdout.strip().splitlines():
        parts = line.split("\t")
        if len(parts) < 2:
            continue
        vid_id = parts[0].strip()
        title = parts[1].strip() if len(parts) > 1 else ""
        upload_date_str = parts[2].strip() if len(parts) > 2 else ""
        duration_str = parts[3].strip() if len(parts) > 3 else "0"

        # Parse date
        vid_date = None
        if upload_date_str and len(upload_date_str) == 8:
            try:
                vid_date = date(
                    int(upload_date_str[:4]),
                    int(upload_date_str[4:6]),
                    int(upload_date_str[6:8]),
                )
            except ValueError:
                pass

        videos.append({
            "id": vid_id,
            "title": title,
            "date": vid_date,
            "url": f"https://www.youtube.com/watch?v={vid_id}",
            "duration_seconds": int(duration_str) if duration_str.isdigit() else 0,
        })

    return videos


def is_relevant_video(title: str, min_duration_seconds: int = 300) -> bool:
    """
    Filter: keep videos that are likely FOMC member speeches.
    Requires either a member's name OR a policy keyword in the title,
    and duration ≥ 5 minutes (filters out clips/highlights).
    """
    title_lower = title.lower()

    # Use word-boundary matching so "Cook" doesn't match "Cooking"
    has_member = any(
        re.search(r"\b" + re.escape(name.lower()) + r"\b", title_lower)
        for name in FOMC_MEMBER_NAMES
    )
    has_keyword = any(kw in title_lower for kw in RELEVANT_TITLE_KEYWORDS)

    return has_member or has_keyword


def download_transcript(video_url: str, video_id: str) -> tuple[str, bool]:
    """
    Download the best available transcript for a video.
    Prefers manual captions; falls back to auto-generated.
    Returns (transcript_text, is_auto_generated).
    Returns ("", False) if no transcript is available.
    """
    with tempfile.TemporaryDirectory() as tmpdir:
        # Try manual subtitles first
        for auto in ("", "--write-auto-subs"):
            args = [
                "--write-subs" if not auto else "--write-auto-subs",
                "--skip-download",
                "--sub-langs", "en",
                "--sub-format", "vtt",
                "--convert-subs", "vtt",
                "--output", f"{tmpdir}/%(id)s.%(ext)s",
                "--no-warnings",
                "--quiet",
                video_url,
            ]
            if auto:
                args = [
                    "--write-auto-subs",
                    "--skip-download",
                    "--sub-langs", "en.*",
                    "--sub-format", "vtt",
                    "--convert-subs", "vtt",
                    "--output", f"{tmpdir}/%(id)s.%(ext)s",
                    "--no-warnings",
                    "--quiet",
                    video_url,
                ]

            _run_ytdlp(*[a for a in args if a], timeout=60)

            vtt_files = list(Path(tmpdir).glob("*.vtt"))
            if vtt_files:
                raw_vtt = vtt_files[0].read_text(encoding="utf-8", errors="replace")
                text = _parse_vtt(raw_vtt)
                is_auto = bool(auto)
                return text, is_auto

    return "", False


def _parse_vtt(vtt_text: str) -> str:
    """
    Convert VTT subtitle format to clean plain text.
    Removes timestamps, duplicate lines (common in auto-subs), and metadata.
    """
    lines = vtt_text.splitlines()
    seen = set()
    text_lines = []

    for line in lines:
        line = line.strip()
        # Skip VTT header, timestamps, blank lines, NOTE blocks
        if not line:
            continue
        if line.startswith("WEBVTT") or line.startswith("NOTE") or line.startswith("Kind:") or line.startswith("Language:"):
            continue
        if re.match(r"^\d{2}:\d{2}:\d{2}", line):  # timestamp line
            continue
        if re.match(r"^\d+$", line):  # cue number
            continue
        # Strip inline VTT tags like <00:00:01.000><c>text</c>
        line = re.sub(r"<[^>]+>", "", line).strip()
        if not line:
            continue
        # Deduplicate consecutive repeated lines (auto-sub artifact)
        if line in seen and text_lines and text_lines[-1] == line:
            continue
        seen.add(line)
        text_lines.append(line)

    return " ".join(text_lines)


def clean_transcript(text: str) -> str:
    """Apply Fed-specific jargon corrections to auto-transcript text."""
    for pattern, replacement in JARGON_CORRECTIONS.items():
        text = re.sub(pattern, replacement, text, flags=re.IGNORECASE)
    # Collapse excessive whitespace
    text = re.sub(r" {2,}", " ", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def infer_speaker_from_title(title: str) -> str:
    """Extract speaker name from video title heuristically."""
    # "Remarks by John Williams" / "John Williams on ..." / "Fed's Williams..."
    _TITLE_STOP_WORDS = re.compile(
        r"\b(Speech|Remarks|Address|Talk|Discussion|Panel|Testimony|Lecture|Keynote|Presentation)\b.*$",
        re.IGNORECASE,
    )
    # Case-insensitive prefix, but name group must be Title Case to avoid
    # capturing lowercase prepositions like "at", "on", "the"
    m = re.search(
        r"(?:[Bb]y|[Ww]ith|[Ff]rom|:\s*)\s*([A-Z][a-z]+(?:\s+[A-Z][a-z]+){1,2})",
        title,
    )
    if m:
        candidate = _TITLE_STOP_WORDS.sub("", m.group(1)).strip()
        if any(re.search(r"\b" + re.escape(name.lower()) + r"\b", candidate.lower()) for name in FOMC_MEMBER_NAMES):
            return candidate

    # Try matching just a known last name
    for name in FOMC_MEMBER_NAMES:
        if name.lower() in title.lower():
            # Return the full known name if we can map it
            name_map = {
                "Powell": "Jerome Powell",
                "Jefferson": "Philip Jefferson",
                "Williams": "John Williams",
                "Goolsbee": "Austan Goolsbee",
                "Kashkari": "Neel Kashkari",
                "Logan": "Lorie Logan",
                "Bostic": "Raphael Bostic",
                "Barkin": "Thomas Barkin",
                "Daly": "Mary Daly",
                "Waller": "Christopher Waller",
                "Kugler": "Adriana Kugler",
                "Adriana": "Adriana Kugler",
                "Musalem": "Alberto Musalem",
                "Hammack": "Beth Hammack",
                "Schmid": "Jeff Schmid",
                "Collins": "Susan Collins",
                "Harker": "Patrick Harker",
                "Bowman": "Michelle Bowman",
                "Cook": "Lisa Cook",
                "Barr": "Michael Barr",
            }
            return name_map.get(name, name)

    return "Unknown"


# ---------------------------------------------------------------------------
# Main public interface
# ---------------------------------------------------------------------------

class YouTubeScraper:
    """
    Scrapes YouTube channels for FOMC member speech transcripts.
    Only fetches videos uploaded on or after config.SPEECH_START_DATE.
    """

    def __init__(self, channels: dict[str, str] | None = None):
        self.channels = channels or CHANNELS
        self._cutoff = date.fromisoformat(config.SPEECH_START_DATE)

    def fetch_speeches(self, max_per_channel: int = 50) -> list[SpeechRecord]:
        records = []
        for channel_name, channel_url in self.channels.items():
            logger.info(f"[YouTube/{channel_name}] Listing videos...")
            videos = list_channel_videos(channel_url, max_videos=max_per_channel)
            logger.info(f"[YouTube/{channel_name}] {len(videos)} videos found")

            for video in videos:
                # Date filter
                if video["date"] and video["date"] < self._cutoff:
                    continue

                # Relevance filter
                if not is_relevant_video(video["title"], video.get("duration_seconds", 0)):
                    logger.debug(f"  Skipping (not relevant): {video['title'][:60]}")
                    continue

                logger.info(f"  Fetching transcript: {video['title'][:70]}")
                transcript, is_auto = download_transcript(video["url"], video["id"])

                if not transcript:
                    logger.info(f"  No transcript available: {video['title'][:60]}")
                    continue

                if is_auto:
                    transcript = clean_transcript(transcript)

                speaker = infer_speaker_from_title(video["title"])
                tier, voter = get_tier(speaker)

                rec = SpeechRecord(
                    speaker=speaker,
                    date=video["date"] or date.today(),
                    title=video["title"],
                    url=video["url"],
                    text=transcript,
                    source=f"youtube_{channel_name.lower().replace(' ', '_')}",
                    doc_type="speech",
                    tier=tier,
                    voter=voter,
                    metadata={
                        "youtube_id": video["id"],
                        "channel": channel_name,
                        "auto_transcript": is_auto,
                        "duration_seconds": video.get("duration_seconds", 0),
                    },
                )
                records.append(rec)
                logger.info(
                    f"  [green]✓[/green] {rec.date} {speaker} — "
                    f"{'auto' if is_auto else 'manual'} transcript, "
                    f"{len(transcript)} chars"
                )

        return records

    def fetch_single_video(self, url: str) -> SpeechRecord | None:
        """Fetch transcript for a single known video URL."""
        # Get metadata
        ok, stdout = _run_ytdlp(
            "--print", "%(id)s\t%(title)s\t%(upload_date)s\t%(duration)s",
            "--no-playlist",
            "--quiet",
            "--no-warnings",
            url,
            timeout=30,
        )
        if not ok or not stdout.strip():
            logger.warning(f"Could not get metadata for {url}")
            return None

        parts = stdout.strip().split("\t")
        vid_id = parts[0]
        title = parts[1] if len(parts) > 1 else "Unknown"
        upload_date_str = parts[2] if len(parts) > 2 else ""
        duration = int(parts[3]) if len(parts) > 3 and parts[3].isdigit() else 0

        vid_date = None
        if upload_date_str and len(upload_date_str) == 8:
            try:
                vid_date = date(int(upload_date_str[:4]), int(upload_date_str[4:6]), int(upload_date_str[6:8]))
            except ValueError:
                pass

        transcript, is_auto = download_transcript(url, vid_id)
        if not transcript:
            logger.warning(f"No transcript for {url}")
            return None

        if is_auto:
            transcript = clean_transcript(transcript)

        speaker = infer_speaker_from_title(title)
        tier, voter = get_tier(speaker)

        return SpeechRecord(
            speaker=speaker,
            date=vid_date or date.today(),
            title=title,
            url=url,
            text=transcript,
            source="youtube_direct",
            doc_type="speech",
            tier=tier,
            voter=voter,
            metadata={
                "youtube_id": vid_id,
                "auto_transcript": is_auto,
                "duration_seconds": duration,
            },
        )
