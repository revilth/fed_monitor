"""
Fed Monitor — daily email sender.
Finds today's report files and sends them via Apple Mail (osascript).
Called automatically by launchd at 6pm on weekdays (non-blackout only).

Requires: Gmail account connected to Apple Mail (System Settings → Internet Accounts → Google).
"""

import logging
import subprocess
import sys
from datetime import date
from pathlib import Path

BASE_DIR = Path(__file__).parent
REPORTS_DIR = BASE_DIR / "data" / "reports" / "daily"
TO_ADDRESS = "thiago_teixeiraferreira@vanguard.com"

# FOMC blackout periods for 2026 — update each January with new calendar.
# Format: (start_date_inclusive, end_date_inclusive)
# Blackout = second Saturday before meeting through day after meeting ends.
BLACKOUT_PERIODS_2026 = [
    (date(2026, 1, 17), date(2026, 1, 30)),   # Jan 28-29 FOMC
    (date(2026, 3,  7), date(2026, 3, 20)),   # Mar 18-19 FOMC
    (date(2026, 4, 18), date(2026, 4, 30)),   # Apr 28-29 FOMC
    (date(2026, 6,  6), date(2026, 6, 19)),   # Jun 17-18 FOMC
    (date(2026, 7, 18), date(2026, 7, 31)),   # Jul 29-30 FOMC
    (date(2026, 9,  5), date(2026, 9, 18)),   # Sep 16-17 FOMC
    (date(2026, 10, 17), date(2026, 10, 30)), # Oct 28-29 FOMC
    (date(2026, 11, 28), date(2026, 12, 11)), # Dec  9-10 FOMC
]

log_file = BASE_DIR / "logs" / "daily_email.log"
log_file.parent.mkdir(exist_ok=True)
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(message)s",
    handlers=[
        logging.FileHandler(log_file),
        logging.StreamHandler(sys.stdout),
    ],
)
logger = logging.getLogger(__name__)


def is_blackout_day(today: date = None) -> bool:
    today = today or date.today()
    return any(start <= today <= end for start, end in BLACKOUT_PERIODS_2026)


def find_todays_reports() -> list[Path]:
    today = date.today().strftime("%Y%m%d")
    return sorted(REPORTS_DIR.glob(f"{today}*.txt"))


def build_subject_and_body(reports: list[Path]) -> tuple[str, str]:
    today_str = date.today().strftime("%B %d, %Y")

    if not reports:
        subject = f"Fed Monitor — {today_str} — No new reports"
        body = f"Fed Monitor — {today_str}\n\nNo new speeches scored today.\n"
        return subject, body

    sections = [p.read_text(encoding="utf-8") for p in reports]
    body = "\n\n".join(sections)

    names = []
    for path in reports:
        parts = path.stem.split("_")
        middle = [p for p in parts[1:] if p.lower() != "daily"]
        names.append(" ".join(middle).replace("pressconf", "Press Conference"))
    subject = f"Fed Monitor — {today_str} — {', '.join(names)}"

    return subject, body


def send_via_apple_mail(subject: str, body: str) -> bool:
    # Escape backslashes and quotes for AppleScript string embedding
    safe_subject = subject.replace("\\", "\\\\").replace('"', '\\"')
    safe_body = body.replace("\\", "\\\\").replace('"', '\\"')

    script = f'''
tell application "Mail"
    set theMessage to make new outgoing message with properties {{\\
        subject:"{safe_subject}", \\
        content:"{safe_body}", \\
        visible:false}}
    tell theMessage
        make new to recipient at end of to recipients \\
            with properties {{address:"{TO_ADDRESS}"}}
    end tell
    send theMessage
end tell
'''
    result = subprocess.run(
        ["osascript", "-e", script],
        capture_output=True,
        text=True,
    )
    if result.returncode == 0:
        logger.info(f"Sent via Apple Mail: {subject}")
        return True
    else:
        logger.error(f"Apple Mail send failed: {result.stderr.strip()}")
        return False


def main():
    logger.info("Fed Monitor daily email — starting")

    if is_blackout_day():
        logger.info("FOMC blackout period — skipping email.")
        sys.exit(0)

    reports = find_todays_reports()
    if not reports:
        logger.info("No reports for today — skipping email.")
        sys.exit(0)

    logger.info(f"Found {len(reports)} report(s): {[r.name for r in reports]}")
    subject, body = build_subject_and_body(reports)
    success = send_via_apple_mail(subject, body)
    sys.exit(0 if success else 1)


if __name__ == "__main__":
    main()
