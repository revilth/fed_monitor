"""
Email delivery for Fed Monitor reports.
Uses Gmail SMTP with an App Password (not the regular Gmail password).
Configure in .env:
  EMAIL_FROM=revilth@gmail.com
  EMAIL_TO=thiago_teixeiraferreira@vanguard.com
  GMAIL_APP_PASSWORD=xxxx-xxxx-xxxx-xxxx
"""
import logging
import smtplib
from datetime import date
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from pathlib import Path

import sys
sys.path.insert(0, str(Path(__file__).parent.parent.parent))
import config

logger = logging.getLogger(__name__)

SMTP_HOST = "smtp.gmail.com"
SMTP_PORT = 587


def _build_message(subject: str, body: str, attachment_path: Path | None = None) -> MIMEMultipart:
    msg = MIMEMultipart()
    msg["From"] = config.EMAIL_FROM
    msg["To"] = config.EMAIL_TO
    msg["Subject"] = subject
    msg.attach(MIMEText(body, "plain"))

    if attachment_path and attachment_path.exists():
        with open(attachment_path, "rb") as f:
            from email.mime.base import MIMEBase
            from email import encoders
            part = MIMEBase("application", "octet-stream")
            part.set_payload(f.read())
            encoders.encode_base64(part)
            part.add_header(
                "Content-Disposition",
                f"attachment; filename={attachment_path.name}",
            )
            msg.attach(part)

    return msg


def send(subject: str, body: str, attachment_path: Path | None = None) -> bool:
    """Send an email. Returns True on success."""
    if not config.EMAIL_FROM or not config.EMAIL_TO or not config.GMAIL_APP_PASSWORD:
        logger.warning("Email not configured — set EMAIL_FROM, EMAIL_TO, GMAIL_APP_PASSWORD in .env")
        return False

    msg = _build_message(subject, body, attachment_path)
    try:
        with smtplib.SMTP(SMTP_HOST, SMTP_PORT) as server:
            server.ehlo()
            server.starttls()
            server.login(config.EMAIL_FROM, config.GMAIL_APP_PASSWORD)
            server.sendmail(config.EMAIL_FROM, config.EMAIL_TO, msg.as_string())
        logger.info(f"Email sent: {subject}")
        return True
    except Exception as e:
        logger.error(f"Email failed: {e}")
        return False


def send_weekly_report(report_path: Path) -> bool:
    today = date.today().strftime("%B %d, %Y")
    subject = f"Fed Monitor Weekly Report — {today}"
    body = report_path.read_text(encoding="utf-8") if report_path.exists() else "Report file not found."
    return send(subject, body, attachment_path=report_path)


def send_alert(alert_text: str, subject: str | None = None) -> bool:
    today = date.today().strftime("%B %d, %Y")
    subject = subject or f"Fed Monitor Alert — {today}"
    return send(subject, alert_text)


def send_scored_summary(speaker: str, scored_path: Path) -> bool:
    """Send notification when a Tier 1 or 2 speech is scored."""
    today = date.today().strftime("%B %d, %Y")
    subject = f"Fed Monitor: New scored speech — {speaker} ({today})"
    body = scored_path.read_text(encoding="utf-8") if scored_path.exists() else "Scored file not found."
    return send(subject, body)
