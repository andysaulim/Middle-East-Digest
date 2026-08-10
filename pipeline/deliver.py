"""
deliver.py — Iran War Update, delivery (Phase 4b)

Delivery mode chosen for v1: AUTO-DRAFT, YOU SEND.

The pipeline does not email the team list. It emails the finished brief to a single
REVIEWER address (you), so it arrives each morning as a ready-to-send draft. You glance,
edit if needed, and forward to DL_Middle_East_Studies. This keeps a human on the
two-source check and needs no access to the team distribution list.

Credentials — two supported styles:

  1. GMAIL (matches the Korea/Japan digests). Set GMAIL_USER, GMAIL_APP_PASS, and
     DIGEST_TO (comma-separated recipients). Sends via Gmail SMTP SSL on port 465,
     exactly like the other digests. Optional GMAIL_FROM overrides the From alias.

  2. GENERIC SMTP (the original Iran config). Set SMTP_HOST, SMTP_USER, SMTP_PASS,
     REVIEWER_EMAIL, and optionally SMTP_PORT (default 587, STARTTLS).

If neither set of credentials is present, delivery falls back to LOCAL mode: it writes
the .html and prints the path for you to open and send yourself.

Later upgrade (documented in README): create a real Outlook draft in your mailbox via the
Microsoft Graph API instead of an SMTP self-email.
"""

import os
import smtplib
import sys
from email.mime.text import MIMEText
from email.utils import formatdate
from datetime import datetime, timezone
from pathlib import Path

OUT_DIR = Path(__file__).parent / "out"


def latest_html():
    files = sorted(OUT_DIR.glob("brief_*.html"))
    if not files:
        sys.exit("No brief_*.html found. Run render.py first.")
    return files[-1]


def _recipients():
    """Recipient list from DIGEST_TO (comma-separated) or REVIEWER_EMAIL."""
    raw = os.environ.get("DIGEST_TO") or os.environ.get("REVIEWER_EMAIL") or ""
    return [addr.strip() for addr in raw.split(",") if addr.strip()]


def _build_message(html, sender, recipients):
    date_label = datetime.now(timezone.utc).strftime("%-m/%-d") \
        if os.name != "nt" else datetime.now(timezone.utc).strftime("%m/%d")
    msg = MIMEText(html, "html", "utf-8")
    msg["Subject"] = f"[DRAFT] Iran War Update ({date_label})"
    msg["From"] = sender
    msg["To"] = ", ".join(recipients)
    msg["Date"] = formatdate(localtime=True)
    return msg


def deliver(html_path=None):
    html_path = Path(html_path) if html_path else latest_html()
    html = html_path.read_text(encoding="utf-8")

    recipients = _recipients()

    gmail_user = os.environ.get("GMAIL_USER")
    gmail_pass = os.environ.get("GMAIL_APP_PASS")

    smtp_host = os.environ.get("SMTP_HOST")
    smtp_user = os.environ.get("SMTP_USER")
    smtp_pass = os.environ.get("SMTP_PASS")

    # 1) Gmail (same env vars as the Korea/Japan digests).
    if recipients and gmail_user and gmail_pass:
        sender = os.environ.get("GMAIL_FROM") or gmail_user
        msg = _build_message(html, sender, recipients)
        with smtplib.SMTP_SSL("smtp.gmail.com", 465) as s:
            s.login(gmail_user, gmail_pass)
            s.send_message(msg)
        print(f"Draft emailed to {', '.join(recipients)} via Gmail ({gmail_user})")
        return

    # 2) Generic SMTP (original Iran config).
    if recipients and smtp_host and smtp_user and smtp_pass:
        sender = smtp_user
        msg = _build_message(html, sender, recipients)
        port = int(os.environ.get("SMTP_PORT") or "587")
        with smtplib.SMTP(smtp_host, port) as s:
            s.starttls()
            s.login(smtp_user, smtp_pass)
            s.send_message(msg)
        print(f"Draft emailed to {', '.join(recipients)} via {smtp_host}")
        return

    # 3) Local mode.
    print("No email credentials set -> local mode. Open and send this file yourself:")
    print("  Gmail path needs GMAIL_USER, GMAIL_APP_PASS, DIGEST_TO;")
    print("  generic SMTP path needs SMTP_HOST, SMTP_USER, SMTP_PASS, REVIEWER_EMAIL.")
    print(f"  {html_path}")


if __name__ == "__main__":
    deliver(sys.argv[1] if len(sys.argv) > 1 else None)
