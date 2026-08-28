"""
deliver.py — Iran War Update, delivery (Phase 4b)

Delivery mode chosen for v1: AUTO-DRAFT, YOU SEND.

The pipeline does not email the team list. It emails the finished brief to a single
REVIEWER address (you), so it arrives each morning as a ready-to-send draft. You glance,
edit if needed, and forward to DL_Middle_East_Studies. This keeps a human on the
two-source check and needs no access to the team distribution list.

Credentials — three supported styles, tried in this order of preference:

  1. OUTLOOK / MICROSOFT GRAPH (nicest UX: a real editable draft in the mailbox, so the
     reviewer just hits Send). Set MS_TENANT_ID, MS_CLIENT_ID, MS_CLIENT_SECRET, and
     MS_MAILBOX. Going live requires CSIS IT to register an Entra (Azure AD) app with the
     Mail.ReadWrite APPLICATION permission and admin consent (see SETUP.md). If Graph is
     configured but errors, delivery falls through to Gmail rather than failing the run.

  2. GMAIL (matches the Korea/Japan digests). Set GMAIL_USER, GMAIL_APP_PASS, and
     DIGEST_TO (comma-separated recipients). Sends via Gmail SMTP SSL on port 465,
     exactly like the other digests. Optional GMAIL_FROM overrides the From alias.

  3. GENERIC SMTP (the original Iran config). Set SMTP_HOST, SMTP_USER, SMTP_PASS,
     REVIEWER_EMAIL, and optionally SMTP_PORT (default 587, STARTTLS).

If none of these are present, delivery falls back to LOCAL mode: it writes the .html and
prints the path for you to open and send yourself.
"""

import os
import json
import smtplib
import sqlite3
import sys
import urllib.parse
import urllib.request
from email.mime.text import MIMEText
from email.utils import formatdate
from datetime import datetime, timezone
from pathlib import Path

import collect  # reuse the archive DB path and the ET timezone

OUT_DIR = Path(__file__).parent / "out"


# --- Once-per-day delivery guard ---------------------------------------------
# GitHub Actions schedules are best-effort: a slot can be DROPPED and then fired hours late,
# and we added a backup cron, so the brief can be triggered more than once on the same day.
# To email the team at most once per calendar day we record the date we delivered in the
# archive DB (which persists across runs, like social.py's X cache). A later run that same day
# skips the send. A manual override run (ALLOW_RESEND=1, set by the workflow when a digest_to
# recipient override is given, i.e. a test to yourself) always sends and never marks the day
# delivered, so it neither is blocked by nor blocks the real scheduled send.

def _brief_date_str(now=None):
    """The brief's own date (America/New_York calendar day) as YYYY-MM-DD — the guard key."""
    now = now or datetime.now(timezone.utc)
    return now.astimezone(collect._ET).strftime("%Y-%m-%d")


def _delivered_today(date_str):
    try:
        con = sqlite3.connect(collect.DB_PATH)
        con.execute("CREATE TABLE IF NOT EXISTS delivered (date TEXT PRIMARY KEY)")
        row = con.execute("SELECT 1 FROM delivered WHERE date=?", (date_str,)).fetchone()
        con.close()
        return row is not None
    except Exception:
        return False


def _mark_delivered(date_str):
    try:
        con = sqlite3.connect(collect.DB_PATH)
        con.execute("CREATE TABLE IF NOT EXISTS delivered (date TEXT PRIMARY KEY)")
        con.execute("INSERT OR REPLACE INTO delivered VALUES (?)", (date_str,))
        con.execute("DELETE FROM delivered WHERE date < ?", (date_str,))   # keep only today
        con.commit()
        con.close()
    except Exception:
        pass


def _is_override_run():
    """True for a manual test run whose recipients were overridden (ALLOW_RESEND=1): it always
    sends and is exempt from the guard, so it never blocks or is blocked by the scheduled send."""
    return os.environ.get("ALLOW_RESEND", "") not in ("", "0", "false", "False")


def latest_html():
    files = sorted(OUT_DIR.glob("brief_*.html"))
    if not files:
        sys.exit("No brief_*.html found. Run render.py first.")
    return files[-1]


def _recipients():
    """Recipient list from DIGEST_TO (comma-separated) or REVIEWER_EMAIL."""
    raw = os.environ.get("DIGEST_TO") or os.environ.get("REVIEWER_EMAIL") or ""
    return [addr.strip() for addr in raw.split(",") if addr.strip()]


def _build_message(html, sender, recipients, subject=None):
    date_label = datetime.now(timezone.utc).strftime("%-m/%-d") \
        if os.name != "nt" else datetime.now(timezone.utc).strftime("%m/%d")
    msg = MIMEText(html, "html", "utf-8")
    msg["Subject"] = subject or f"[DRAFT] Iran War Update ({date_label})"
    msg["From"] = sender
    msg["To"] = ", ".join(recipients)
    msg["Date"] = formatdate(localtime=True)
    return msg


def _graph_token(tenant, client_id, client_secret):
    """Client-credentials access token for Microsoft Graph."""
    data = urllib.parse.urlencode({
        "grant_type": "client_credentials",
        "client_id": client_id,
        "client_secret": client_secret,
        "scope": "https://graph.microsoft.com/.default",
    }).encode()
    url = f"https://login.microsoftonline.com/{tenant}/oauth2/v2.0/token"
    req = urllib.request.Request(url, data=data,
                                 headers={"Content-Type": "application/x-www-form-urlencoded"})
    resp = json.loads(urllib.request.urlopen(req, timeout=30).read())
    return resp["access_token"]


def _create_outlook_draft(html, subject, recipients, mailbox, token):
    """Create an editable draft in the mailbox via Graph (POST /messages makes a draft)."""
    body = json.dumps({
        "subject": subject,
        "body": {"contentType": "HTML", "content": html},
        "toRecipients": [{"emailAddress": {"address": a}} for a in recipients],
    }).encode()
    url = f"https://graph.microsoft.com/v1.0/users/{urllib.parse.quote(mailbox)}/messages"
    req = urllib.request.Request(url, data=body, headers={
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json",
    })
    urllib.request.urlopen(req, timeout=30).read()


def deliver(html_path=None, subject=None):
    html_path = Path(html_path) if html_path else latest_html()
    html = html_path.read_text(encoding="utf-8")

    recipients = _recipients()
    subject = subject or f"[DRAFT] Iran War Update ({datetime.now(timezone.utc).strftime('%m/%d')})"

    # Once-per-day guard: skip a real send if today's brief already went out, unless this is a
    # manual override/resend run. (Local mode below is not a send, so it is never guarded.)
    override = _is_override_run()
    today = _brief_date_str()
    guard_on = recipients and not override
    if guard_on and _delivered_today(today):
        print(f"Already delivered the brief for {today}; skipping duplicate send "
              "(set ALLOW_RESEND=1 to force). No email sent.")
        return

    # 0) Outlook / Microsoft Graph draft (preferred when fully configured). Best-effort: on
    #    any error, log and fall through to Gmail so a misconfigured Graph never drops the run.
    ms_tenant = os.environ.get("MS_TENANT_ID")
    ms_client = os.environ.get("MS_CLIENT_ID")
    ms_secret = os.environ.get("MS_CLIENT_SECRET")
    ms_mailbox = os.environ.get("MS_MAILBOX")
    if recipients and ms_tenant and ms_client and ms_secret and ms_mailbox:
        try:
            token = _graph_token(ms_tenant, ms_client, ms_secret)
            _create_outlook_draft(html, subject, recipients, ms_mailbox, token)
            print(f"Draft created in Outlook mailbox {ms_mailbox} via Microsoft Graph")
            if not override:
                _mark_delivered(today)
            return
        except Exception as e:
            print(f"Outlook/Graph delivery failed ({e!r}); falling back to Gmail/SMTP.")

    gmail_user = os.environ.get("GMAIL_USER")
    gmail_pass = os.environ.get("GMAIL_APP_PASS")

    smtp_host = os.environ.get("SMTP_HOST")
    smtp_user = os.environ.get("SMTP_USER")
    smtp_pass = os.environ.get("SMTP_PASS")

    # 1) Gmail (same env vars as the Korea/Japan digests).
    if recipients and gmail_user and gmail_pass:
        sender = os.environ.get("GMAIL_FROM") or gmail_user
        msg = _build_message(html, sender, recipients, subject)
        with smtplib.SMTP_SSL("smtp.gmail.com", 465) as s:
            s.login(gmail_user, gmail_pass)
            s.send_message(msg)
        print(f"Draft emailed to {', '.join(recipients)} via Gmail ({gmail_user})")
        if not override:
            _mark_delivered(today)
        return

    # 2) Generic SMTP (original Iran config).
    if recipients and smtp_host and smtp_user and smtp_pass:
        sender = smtp_user
        msg = _build_message(html, sender, recipients, subject)
        port = int(os.environ.get("SMTP_PORT") or "587")
        with smtplib.SMTP(smtp_host, port) as s:
            s.starttls()
            s.login(smtp_user, smtp_pass)
            s.send_message(msg)
        print(f"Draft emailed to {', '.join(recipients)} via {smtp_host}")
        if not override:
            _mark_delivered(today)
        return

    # 4) Local mode.
    print("No email credentials set -> local mode. Open and send this file yourself:")
    print("  Outlook/Graph path needs MS_TENANT_ID, MS_CLIENT_ID, MS_CLIENT_SECRET, MS_MAILBOX;")
    print("  Gmail path needs GMAIL_USER, GMAIL_APP_PASS, DIGEST_TO;")
    print("  generic SMTP path needs SMTP_HOST, SMTP_USER, SMTP_PASS, REVIEWER_EMAIL.")
    print(f"  {html_path}")


def _selftest():
    """Offline test of the once-per-day guard against a throwaway DB (no network, no send)."""
    import tempfile
    orig_db = collect.DB_PATH
    collect.DB_PATH = tempfile.mktemp(suffix=".db")
    try:
        assert not _delivered_today("2026-08-27")
        _mark_delivered("2026-08-27")
        assert _delivered_today("2026-08-27")
        # A newer day prunes the older row (the table holds only the latest delivered date).
        _mark_delivered("2026-08-28")
        assert _delivered_today("2026-08-28") and not _delivered_today("2026-08-27")
        # Override detection.
        for v in ("", "0", "false", "False"):
            os.environ["ALLOW_RESEND"] = v
            assert not _is_override_run(), v
        for v in ("1", "true", "yes"):
            os.environ["ALLOW_RESEND"] = v
            assert _is_override_run(), v
        os.environ.pop("ALLOW_RESEND", None)
    finally:
        collect.DB_PATH = orig_db
    print("deliver.py self-test passed")


if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1] == "--selftest":
        _selftest()
    else:
        deliver(sys.argv[1] if len(sys.argv) > 1 else None)
