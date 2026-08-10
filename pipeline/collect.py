"""
collect.py — Iran War Update, live collector (Phase 1)

Pulls the day's Iran-war items from free, keyless sources:
  1. Google News RSS search queries (the main relevance engine)
  2. Direct outlet RSS feeds (Al Jazeera, Times of Israel, Al Arabiya), keyword-filtered
  3. GDELT DOC 2.0 API as an event backbone

Normalizes everything to a common record, dedupes, and writes both a dated JSON file
(for the digest step) and a SQLite archive (the queryable corpus).

Stdlib only — no pip install needed to run this file.
"""

import urllib.request
import urllib.parse
import xml.etree.ElementTree as ET
import json
import sqlite3
import re
import os
import time
from datetime import datetime, timezone
from pathlib import Path

DATA_DIR = Path(__file__).parent / "data"
DATA_DIR.mkdir(exist_ok=True)
DB_PATH = DATA_DIR / "archive.db"

UA = {"User-Agent": "Mozilla/5.0 (IranWarUpdate collector)"}

# --- Source configuration -------------------------------------------------

# Google News RSS search: keyless, query-driven, returns real outlet attribution.
GOOGLE_NEWS_QUERIES = [
    "Iran Strait of Hormuz",
    "Iran US negotiations Trump",
    "Houthi tanker Red Sea",
    "Israel Lebanon strike Hezbollah",
    "Iran nuclear IRGC",
    "Yemen Saudi Arabia Houthi",
    "Iran Oman Hormuz deal",
]

# Direct outlet feeds (mixed-topic; filtered by KEYWORDS below).
DIRECT_FEEDS = [
    ("Al Jazeera", "https://www.aljazeera.com/xml/rss/all.xml"),
    ("Times of Israel", "https://www.timesofisrael.com/feed/"),
    ("Al Arabiya", "https://english.alarabiya.net/.mrss/en.xml"),
]

# Relevance filter for the mixed-topic direct feeds.
KEYWORDS = [
    "iran", "tehran", "hormuz", "houthi", "irgc", "hezbollah", "lebanon",
    "israel", "idf", "yemen", "saudi", "tanker", "strait", "araghchi",
    "pezeshkian", "oman", "red sea", "bab el mandeb", "nuclear", "blockade",
    "netanyahu", "unifil", "centcom",
]

GDELT_QUERY = '(Iran (Hormuz OR Houthi OR nuclear OR strike))'


# --- Helpers --------------------------------------------------------------

def _fetch(url, timeout=30):
    req = urllib.request.Request(url, headers=UA)
    return urllib.request.urlopen(req, timeout=timeout).read()


def _clean(text):
    if not text:
        return ""
    text = re.sub(r"<[^>]+>", "", text)          # strip any HTML
    text = re.sub(r"\s+", " ", text).strip()
    return text


def _norm_key(title):
    """Loose key for cross-source dedupe: lowercase alphanumerics only."""
    return re.sub(r"[^a-z0-9]", "", (title or "").lower())[:80]


def _is_relevant(text):
    t = (text or "").lower()
    return any(k in t for k in KEYWORDS)


# --- Collectors -----------------------------------------------------------

def from_rss(source_name, url, filter_relevant=False):
    out = []
    try:
        root = ET.fromstring(_fetch(url))
    except Exception as e:
        print(f"  [rss] {source_name} ERR: {e!r}")
        return out
    for it in root.findall(".//item"):
        title = _clean(it.findtext("title"))
        link = (it.findtext("link") or "").strip()
        summary = _clean(it.findtext("description"))
        pub = (it.findtext("pubDate") or "").strip()
        # Google News tags the real outlet in a <source> element.
        src_el = it.find("source")
        outlet = _clean(src_el.text) if src_el is not None else source_name
        if filter_relevant and not _is_relevant(f"{title} {summary}"):
            continue
        if not title or not link:
            continue
        out.append({
            "source": outlet,
            "collector": source_name,
            "title": title,
            "url": link,
            "summary": summary,
            "published": pub,
        })
    print(f"  [rss] {source_name}: {len(out)} items")
    return out


def from_google_news(query):
    q = urllib.parse.quote(f"{query} when:1d")
    url = f"https://news.google.com/rss/search?q={q}&hl=en-US&gl=US&ceid=US:en"
    return from_rss(f"Google News: {query}", url)


def from_gdelt(query, retries=3):
    q = urllib.parse.quote(query)
    url = (f"https://api.gdeltproject.org/api/v2/doc/doc?query={q}"
           f"&mode=ArtList&maxrecords=50&format=json&timespan=24h")
    for attempt in range(retries):
        try:
            data = json.loads(_fetch(url))
            arts = data.get("articles", [])
            out = [{
                "source": a.get("domain", "GDELT"),
                "collector": "GDELT",
                "title": _clean(a.get("title")),
                "url": a.get("url", ""),
                "summary": "",
                "published": a.get("seendate", ""),
            } for a in arts if a.get("title") and a.get("url")]
            print(f"  [gdelt]: {len(out)} items")
            return out
        except Exception as e:
            if attempt < retries - 1:
                time.sleep(5)  # GDELT rate-limits; back off and retry
            else:
                print(f"  [gdelt] ERR after {retries} tries: {e!r}")
    return []


# --- Archive --------------------------------------------------------------

def init_db():
    con = sqlite3.connect(DB_PATH)
    con.execute("""
        CREATE TABLE IF NOT EXISTS items (
            url TEXT PRIMARY KEY,
            collected_date TEXT,
            source TEXT,
            collector TEXT,
            title TEXT,
            summary TEXT,
            published TEXT
        )
    """)
    con.commit()
    return con


def archive(con, items, date_str):
    new = 0
    for it in items:
        try:
            cur = con.execute(
                "INSERT OR IGNORE INTO items VALUES (?,?,?,?,?,?,?)",
                (it["url"], date_str, it["source"], it["collector"],
                 it["title"], it["summary"], it["published"]),
            )
            new += cur.rowcount  # 1 if inserted, 0 if URL already archived
        except Exception:
            pass
    con.commit()
    return new


# --- Main -----------------------------------------------------------------

def collect():
    date_str = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    print(f"Collecting Iran War Update items for {date_str} (UTC)")

    items = []
    print("Google News queries:")
    for q in GOOGLE_NEWS_QUERIES:
        items += from_google_news(q)
    print("Direct feeds:")
    for name, url in DIRECT_FEEDS:
        items += from_rss(name, url, filter_relevant=True)
    print("GDELT:")
    items += from_gdelt(GDELT_QUERY)

    # Cross-source dedupe by loose title key, keeping the first (best) source.
    seen, deduped = set(), []
    for it in items:
        k = _norm_key(it["title"])
        if k and k not in seen:
            seen.add(k)
            deduped.append(it)
    print(f"\n{len(items)} raw -> {len(deduped)} after dedupe")

    con = init_db()
    new = archive(con, deduped, date_str)
    con.close()
    print(f"Archived {new} new items to {DB_PATH}")

    out_path = DATA_DIR / f"items_{date_str}.json"
    out_path.write_text(json.dumps(deduped, indent=2, ensure_ascii=False),
                        encoding="utf-8")
    print(f"Wrote {out_path}")
    return out_path


if __name__ == "__main__":
    collect()
