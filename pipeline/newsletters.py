"""
newsletters.py — Iran War Update, subscriber-only newsletter ingestion

The team borrows heavily from three newsletters that have no public feed: Al-Monitor
"Middle East Today", The National "Daily Briefing", and Semafor "Flagship". Because they are
subscriber-only, the reliable source is the delivered email — there is no paywall to defeat,
the content is sent to us. The pipeline logs into the Gmail inbox that receives them (reusing
GMAIL_USER / GMAIL_APP_PASS, the same secrets deliver.py uses to send) over IMAP, reads the
day's issues, parses the email HTML directly, and extracts the article links and blurbs.
Semafor Flagship also has a public web edition, used as a fallback for that one only.

Best-effort: no creds, IMAP disabled, or a missing issue just yields fewer items. Disable
with NEWSLETTERS=0.

Prereqs (one-time): subscribe that inbox to the three newsletters, and enable IMAP on the
Gmail account (Settings -> Forwarding and POP/IMAP -> Enable IMAP).

Stdlib only.
"""

import email
import imaplib
import os
import re
import urllib.request
from datetime import datetime, timezone, timedelta
from email.header import decode_header
from urllib.parse import urlparse

import collect  # reuse UA, _clean, _is_relevant

ENABLED = os.environ.get("NEWSLETTERS", "1") not in ("0", "false", "False", "")
IMAP_HOST = "imap.gmail.com"

# A newsletter is identified from its sender (publisher) and/or its subject (newsletter name),
# so whichever ones the inbox is subscribed to are picked up. Add a line to either list to
# recognize a new one.
_PUBLISHERS = [
    ("al-monitor", "Al-Monitor"), ("almonitor", "Al-Monitor"),
    ("thenationalnews", "The National"), ("thenational", "The National"),
    ("the national", "The National"), ("semafor", "Semafor"),
]
_NEWSLETTERS = [
    ("middle east today", "Middle East Today"),
    ("uae today", "UAE Today"),
    ("editor's briefing", "The Editor's Briefing"),
    ("editors briefing", "The Editor's Briefing"),
    ("daily briefing", "Daily Briefing"),
    ("flagship", "Flagship"),
]

# Links that are never article links.
_SKIP_LINK = re.compile(
    r"(unsubscribe|/unsub|list-manage|mailchi|emailcampaign|/preferences|/profile|"
    r"twitter\.com|x\.com|facebook\.com|instagram\.com|linkedin\.com|youtube\.com|"
    r"mailto:|\.gif|\.png|\.jpg|\.jpeg)", re.IGNORECASE)
_A_RE = re.compile(r'<a\s[^>]*href="([^"#]+)"[^>]*>(.*?)</a>', re.DOTALL | re.IGNORECASE)
_TAG_RE = re.compile(r"<[^>]+>")


def _decode(s):
    try:
        return "".join(
            (b.decode(enc or "utf-8", "ignore") if isinstance(b, bytes) else b)
            for b, enc in decode_header(s or ""))
    except Exception:
        return s or ""


def _match_source(frm, subj):
    """Identify a subscribed newsletter from its sender and/or subject; else None."""
    hay = f"{frm} {subj}".lower()
    pub = next((label for key, label in _PUBLISHERS if key in hay), None)
    name = next((disp for key, disp in _NEWSLETTERS if key in hay), None)
    if pub and name:
        return f"{pub} ({name})"
    if pub:
        return f"{pub} (Newsletter)"
    if name:
        return name
    return None


def _looks_like_article(url):
    """True only for a real article URL, not a homepage/section page (which is why an
    Al-Monitor link pointed at the site root). Article slugs are long and hyphenated or
    carry an id; section roots are empty or a short single word."""
    try:
        path = urlparse(url).path.rstrip("/")
    except Exception:
        return False
    if not path:
        return False                                   # homepage
    low = path.lower()
    if any(seg in low for seg in
           ("/newsletters", "/newsletter", "/tag/", "/tags/", "/topics/", "/topic/",
            "/author/", "/authors/", "/category/", "/categories/", "/subscribe",
            "/about", "/section/", "/live/", "/video/", "/videos/")):
        return False
    last = path.split("/")[-1]
    return len(last) >= 12 and ("-" in last or any(c.isdigit() for c in last))


def _html_part(msg):
    """The text/html body of an email message, or ''."""
    parts = msg.walk() if msg.is_multipart() else [msg]
    for part in parts:
        if part.get_content_type() == "text/html":
            try:
                return part.get_payload(decode=True).decode(
                    part.get_content_charset() or "utf-8", "ignore")
            except Exception:
                continue
    return ""


def parse_newsletter_html(html, label, published=""):
    """Extract Iran-relevant {source,collector,title,url,summary,published} from a newsletter."""
    out, seen = [], set()
    for m in _A_RE.finditer(html or ""):
        url = m.group(1).strip()
        text = collect._clean(_TAG_RE.sub(" ", m.group(2)))
        if not url.startswith("http") or _SKIP_LINK.search(url):
            continue
        if not _looks_like_article(url):       # drop homepage / section links
            continue
        if len(text) < 25:                     # skip "read more", icons, nav
            continue
        if url in seen:
            continue
        seen.add(url)
        if not collect._is_relevant(text):     # keep only Iran-war-relevant items
            continue
        out.append({
            "source": label, "collector": "Newsletter",
            "title": text[:280], "url": url, "summary": "", "published": published,
        })
    return out


def from_imap(days=1):
    user = os.environ.get("GMAIL_USER")
    pw = os.environ.get("GMAIL_APP_PASS")
    if not (user and pw):
        print("  [newsletter] no GMAIL_USER/GMAIL_APP_PASS; skipping IMAP")
        return []
    out = []
    try:
        M = imaplib.IMAP4_SSL(IMAP_HOST)
        M.login(user, pw)
        M.select("INBOX")
        since = (datetime.now(timezone.utc) - timedelta(days=days)).strftime("%d-%b-%Y")
        _, data = M.search(None, f"(SINCE {since})")
        ids = data[0].split() if data and data[0] else []
        for mid in ids[-100:]:
            _, md = M.fetch(mid, "(RFC822)")
            if not md or not md[0]:
                continue
            msg = email.message_from_bytes(md[0][1])
            label = _match_source(str(msg.get("From", "")), _decode(msg.get("Subject", "")))
            if not label:
                continue
            items = parse_newsletter_html(_html_part(msg), label,
                                          published=msg.get("Date", ""))
            print(f"  [newsletter] {label}: {len(items)} links")
            out += items
        M.logout()
    except Exception as e:
        print(f"  [newsletter] IMAP ERR: {e!r}")
    return out


SEMAFOR_FLAGSHIP = "https://www.semafor.com/newsletters/flagship"


def from_semafor_web():
    """Public web fallback for Semafor Flagship only (the two others have no public edition)."""
    try:
        req = urllib.request.Request(SEMAFOR_FLAGSHIP, headers=collect.UA)
        html = urllib.request.urlopen(req, timeout=15).read().decode("utf-8", "ignore")
    except Exception as e:
        print(f"  [newsletter] Semafor web ERR: {e!r}")
        return []
    items = parse_newsletter_html(html, "Semafor (Flagship)")
    print(f"  [newsletter] Semafor web: {len(items)} links")
    return items


def collect_newsletters(days=1):
    if not ENABLED:
        print("  [newsletter] disabled (NEWSLETTERS=0)")
        return []
    out = from_imap(days=days)
    if not any(it["source"].startswith("Semafor") for it in out):
        out += from_semafor_web()          # fill Semafor from the web if the email was missing
    return out


if __name__ == "__main__":
    html = """
    <html><body>
    <a href="https://www.al-monitor.com/originals/2026/08/iran-hormuz-deal">Iran and Oman near a deal on Strait of Hormuz shipping lanes</a>
    <a href="https://www.al-monitor.com/">Al-Monitor reported on Iran and the Strait of Hormuz today</a>
    <a href="https://emailcampaign.al-monitor.com/t/t-e-abc">View in browser</a>
    <a href="https://www.al-monitor.com/unsubscribe">Unsubscribe</a>
    <a href="https://twitter.com/almonitor">Follow us</a>
    <a href="https://www.al-monitor.com/x">Read more</a>
    <a href="https://www.al-monitor.com/originals/2026/08/gardening">Ten tips for a better tomato harvest this summer</a>
    </body></html>"""
    items = parse_newsletter_html(html, "Al-Monitor (Middle East Today)")
    assert len(items) == 1, items                        # only the real Iran article survives
    assert "Hormuz" in items[0]["title"]
    assert items[0]["url"].endswith("iran-hormuz-deal")
    assert all(u["url"] != "https://www.al-monitor.com/" for u in items)   # homepage rejected
    # article-link filter
    assert _looks_like_article("https://www.al-monitor.com/originals/2026/08/iran-hormuz-deal")
    assert not _looks_like_article("https://www.al-monitor.com/")
    assert not _looks_like_article("https://www.thenationalnews.com/mena/")
    assert _looks_like_article("https://www.thenationalnews.com/news/mena/2026/08/24/iran-oman-hormuz-talks/")
    # sender + subject matcher
    assert _match_source("news@semafor.com", "Flagship: the world today") == "Semafor (Flagship)"
    assert _match_source("newsletters@thenationalnews.com", "Middle East Today") == "The National (Middle East Today)"
    assert _match_source("noreply@thenationalnews.com", "The Editor's Briefing") == "The National (The Editor's Briefing)"
    assert _match_source("a@b.com", "random unrelated subject") is None
    print("newsletters.py self-test passed")
