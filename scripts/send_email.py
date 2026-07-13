#!/usr/bin/env python3
"""
Ad-hoc email sender for the Fed Communication Monitor.

Sends a one-off email via Gmail SMTP using the SAME account and mechanism as the
daily-report GitHub Action (`.github/workflows/email.yml`): login as
revilresearch@gmail.com with a Gmail App Password, send over SMTP_SSL:465.

The App Password is read from a LOCAL, gitignored file so no secret is ever
committed or passed through GitHub:

    Credential source (first match wins):
      1) --password-file PATH
      2) env var  GMAIL_APP_PASSWORD
      3) ~/.fedmonitor_smtp            (default)

    File format: either the bare 16-char App Password on its own line, or a
    line of the form  GMAIL_APP_PASSWORD=xxxx xxxx xxxx xxxx
    (spaces are stripped automatically, matching Gmail's display format).

This script SENDS immediately. It is intended to be run only when the user
explicitly asks for an email to be sent.

Examples
--------
    # body from a file (preferred for anything multi-line)
    python3 scripts/send_email.py \
        --subject "Fed Monitor — Ad hoc: trimmed-mean PCE in prior MPRs" \
        --body-file /tmp/answer.txt

    # inline body
    python3 scripts/send_email.py \
        --subject "Quick note" --body "One-line message."

    # explicit recipient override
    python3 scripts/send_email.py \
        --to thiago_teixeiraferreira@vanguard.com \
        --subject "..." --body-file note.txt
"""
import argparse
import os
import smtplib
import ssl
import stat
import sys
from email.mime.text import MIMEText
from email.utils import formatdate, make_msgid
from pathlib import Path

# This project sends ONLY from revilresearch@gmail.com and defaults to the same
# work recipient as the daily-report pipeline. The personal address
# revilth@gmail.com is deliberately NOT used anywhere in this project.
LOGIN_USER = "revilresearch@gmail.com"     # whose App Password this is
DEFAULT_FROM = "revilresearch@gmail.com"
DEFAULT_TO = "thiago_teixeiraferreira@vanguard.com"   # matches email.yml
DEFAULT_PW_FILE = Path.home() / ".fedmonitor_smtp"


def load_password(explicit_file: str | None) -> str:
    # 1) explicit file
    if explicit_file:
        return _read_pw_file(Path(explicit_file))
    # 2) environment
    env = os.environ.get("GMAIL_APP_PASSWORD")
    if env:
        return env.replace(" ", "").strip()
    # 3) default file
    if DEFAULT_PW_FILE.exists():
        return _read_pw_file(DEFAULT_PW_FILE)
    sys.exit(
        f"No App Password found. Create {DEFAULT_PW_FILE} containing your Gmail "
        f"App Password, or set GMAIL_APP_PASSWORD, or pass --password-file.\n"
        f"See the module docstring for the file format."
    )


def _read_pw_file(path: Path) -> str:
    if not path.exists():
        sys.exit(f"Password file not found: {path}")
    # gentle permission warning — the file holds a live credential
    mode = path.stat().st_mode
    if mode & (stat.S_IRWXG | stat.S_IRWXO):
        print(
            f"WARNING: {path} is group/world-accessible. "
            f"Run: chmod 600 {path}",
            file=sys.stderr,
        )
    raw = path.read_text(encoding="utf-8").strip()
    # allow either a bare password or KEY=VALUE lines
    for line in raw.splitlines():
        line = line.strip()
        if line.upper().startswith("GMAIL_APP_PASSWORD"):
            _, _, val = line.partition("=")
            return val.replace(" ", "").strip()
    return raw.replace(" ", "").strip()


def main() -> int:
    p = argparse.ArgumentParser(
        description="Send a one-off email via the Fed Monitor Gmail account.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    p.add_argument("--to", action="append", metavar="ADDR",
                   help=f"Recipient (repeatable). Default: {DEFAULT_TO}")
    p.add_argument("--cc", action="append", metavar="ADDR", help="CC (repeatable).")
    p.add_argument("--bcc", action="append", metavar="ADDR", help="BCC (repeatable).")
    p.add_argument("--subject", help="Subject line. (required unless --verify)")
    g = p.add_mutually_exclusive_group()
    g.add_argument("--body", help="Inline plain-text body.")
    g.add_argument("--body-file", help="Path to a UTF-8 plain-text body file.")
    p.add_argument("--from", dest="from_addr", default=DEFAULT_FROM,
                   help=f"From display address. Default: {DEFAULT_FROM}")
    p.add_argument("--password-file", help="Path to a file holding the App Password.")
    p.add_argument("--dry-run", action="store_true",
                   help="Build the message and print a summary, but do NOT send.")
    p.add_argument("--verify", action="store_true",
                   help="Connect and authenticate to Gmail SMTP, then quit. "
                        "Sends NO email. Use to confirm the App Password works.")
    args = p.parse_args()

    # --verify: prove the credential + SMTP login work, send nothing.
    if args.verify:
        password = load_password(args.password_file)
        ctx = ssl.create_default_context()
        with smtplib.SMTP_SSL("smtp.gmail.com", 465, context=ctx) as server:
            server.login(LOGIN_USER, password)
            server.noop()
        print(f"OK: authenticated to Gmail SMTP as {LOGIN_USER}. No email sent.")
        return 0

    if not args.subject or (args.body is None and args.body_file is None):
        p.error("--subject and one of --body/--body-file are required "
                "(unless using --verify).")

    to = args.to or [DEFAULT_TO]
    body = args.body if args.body is not None else \
        Path(args.body_file).read_text(encoding="utf-8")

    msg = MIMEText(body, "plain", "utf-8")
    msg["Subject"] = args.subject
    msg["From"] = args.from_addr
    msg["To"] = ", ".join(to)
    if args.cc:
        msg["Cc"] = ", ".join(args.cc)
    msg["Date"] = formatdate(localtime=True)
    msg["Message-ID"] = make_msgid(domain="gmail.com")

    recipients = list(to) + (args.cc or []) + (args.bcc or [])

    print(f"From:    {args.from_addr}")
    print(f"To:      {', '.join(to)}")
    if args.cc:
        print(f"Cc:      {', '.join(args.cc)}")
    if args.bcc:
        print(f"Bcc:     {', '.join(args.bcc)}")
    print(f"Subject: {args.subject}")
    print(f"Body:    {len(body)} chars")

    if args.dry_run:
        print("\n[dry-run] Not sent.")
        return 0

    password = load_password(args.password_file)
    ctx = ssl.create_default_context()
    with smtplib.SMTP_SSL("smtp.gmail.com", 465, context=ctx) as server:
        server.login(LOGIN_USER, password)
        server.send_message(msg, from_addr=args.from_addr, to_addrs=recipients)

    print(f"\nSent to {len(recipients)} recipient(s).")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
