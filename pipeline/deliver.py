"""
deliver.py — Iran War Update, delivery (Phase 4b)

Delivery mode chosen for v1: AUTO-DRAFT, YOU SEND.

The pipeline does not email the team list. It emails the finished brief to a single
REVIEWER address (you), so it arrives each morning as a ready-to-send draft. You glance,
edit if needed, and forward to DL_Middle_East_Studies. This keeps a human on the
two-source check and needs no access to the team distribution list.

Two ways to run it:
  - LOCAL / no creds: just writes the .html; you open and send it yourself.
  - AUTOMATED (GitHub Actions): if SMTP_HOST/SMTP_USER/SMTP_PASS/REVIEWER_EMAIL are set,
    it emails the brief to REVIEWER_EMAIL via SMTP.

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


def deliver(html_path=None):
    html_path = Path(html_path) if html_path else latest_html()
    html = html_path.read_text(encoding="utf-8")

    reviewer = os.environ.get("REVIEWER_EMAIL")
    host = os.environ.get("SMTP_HOST")
    user = os.environ.get("SMTP_USER")
    pw = os.environ.get("SMTP_PASS")

    if not (reviewer and host and user and pw):
        print("SMTP env not set -> local mode. Open and send this file yourself:")
        print(f"  {html_path}")
        return

    date_label = datetime.now(timezone.utc).strftime("%-m/%-d") \
        if os.name != "nt" else datetime.now(timezone.utc).strftime("%m/%d")
    msg = MIMEText(html, "html", "utf-8")
    msg["Subject"] = f"[DRAFT] Iran War Update ({date_label})"
    msg["From"] = user
    msg["To"] = reviewer
    msg["Date"] = formatdate(localtime=True)

    port = int(os.environ.get("SMTP_PORT", "587"))
    with smtplib.SMTP(host, port) as s:
        s.starttls()
        s.login(user, pw)
        s.send_message(msg)
    print(f"Draft emailed to {reviewer} via {host}")


if __name__ == "__main__":
    deliver(sys.argv[1] if len(sys.argv) > 1 else None)
