"""
collect.py — Iran War Update, live collector (Phase 1)

Pulls the day's Iran-war items from free, keyless sources:
  1. Google News RSS search queries (the main relevance engine)
  2. Al Jazeera live blog + Middle East section (the human tracker's backbone), scraped
     for canonical article links
  3. Direct outlet RSS feeds (Times of Israel, Al Arabiya), keyword-filtered
  4. GDELT DOC 2.0 API as an event backbone
  5. A manual injection file for items no scraper reaches (X / Truth Social / YouTube),
     which an editor drops in by hand

Normalizes everything to a common record, dedupes (preferring prestige / canonical
sources), canonicalizes Google News redirect links to real publisher URLs (resolve.py),
and writes both a dated JSON file (for the digest step) and a SQLite archive (the
queryable corpus).

Lookback window: 1 day on Tue-Fri, 3 days on Monday so the Monday brief carries the
weekend (Saturday, Sunday, and Monday morning up to the ~7am ET send). Override with the
LOOKBACK_DAYS env var after a holiday.

Stdlib only.
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

import resolve
import social

DATA_DIR = Path(__file__).parent / "data"
DATA_DIR.mkdir(exist_ok=True)
DB_PATH = DATA_DIR / "archive.db"

# A browser-like User-Agent: the "collector" UA got 403s from Times of Israel, Al Arabiya,
# and Al Jazeera, which block obvious scripts. This lifts most of those blocks.
UA = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                    "AppleWebKit/537.36 (KHTML, like Gecko) "
                    "Chrome/120.0 Safari/537.36"}

# Sources whose duplicate is preferred when the same story appears twice (matched against
# the item's source/collector). Canonical publisher wins over a Google News redirect.
PRESTIGE_HINTS = [
    "reuters", "associated press", "ap news", "wall street journal", "wsj",
    "new york times", "nyt", "financial times", "bloomberg", "washington post",
    "the economist", "bbc", "al jazeera", "axios", "guardian",
]

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
    "Lebanon Israeli strike UNIFIL casualties",
    "Yemen Houthi Marib Hadramout attack",
    "Strait of Hormuz shipping UKMTO transit toll",
    "Iran Araghchi Gulf states warning",
    "Pezeshkian Iran statement",
    # Regions the human tracker covers that v1 missed:
    "Iraq militia US forces Iran",
    "Egypt Suez Canal Red Sea shipping",
    "Jordan Israel Iran airspace drones",
    "Syria Israel strike Iran militia",
    "Caspian Sea Iran Russia corridor",
    # Outlet-focused fallbacks (reach ToI even when its direct feed 403s):
    "Iran war site:aljazeera.com",
    "Iran OR Hezbollah OR Houthi site:timesofisrael.com",
]

# Al Jazeera pages scraped for canonical article links (the live blog is under /news/liveblog/).
ALJAZEERA_PAGES = [
    ("Al Jazeera Middle East", "https://www.aljazeera.com/where/middle-east/"),
    ("Al Jazeera News", "https://www.aljazeera.com/news/"),
]

# Direct outlet RSS feeds (mixed-topic; filtered by KEYWORDS below).
DIRECT_FEEDS = [
    ("Times of Israel", "https://www.timesofisrael.com/feed/"),
    ("Al Arabiya", "https://english.alarabiya.net/.mrss/en.xml"),
]

# Relevance filter for the mixed-topic direct feeds and scraped links.
KEYWORDS = [
    "iran", "tehran", "hormuz", "houthi", "irgc", "hezbollah", "lebanon",
    "israel", "idf", "yemen", "saudi", "tanker", "strait", "araghchi",
    "pezeshkian", "oman", "red sea", "bab el mandeb", "nuclear", "blockade",
    "netanyahu", "unifil", "centcom", "iraq", "syria", "jordan", "egypt",
    "suez", "caspian", "gulf", "khamenei", "nasrallah", "beirut",
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


def _is_prestige(it):
    s = f"{it.get('source','')} {it.get('collector','')}".lower()
    return any(p in s for p in PRESTIGE_HINTS)


def _lookback_days():
    """1 day normally; 3 on Monday so the brief carries the weekend. LOOKBACK_DAYS overrides."""
    override = os.environ.get("LOOKBACK_DAYS")
    if override and override.isdigit():
        return int(override)
    # Monday == 0. The cron runs ~7:30am ET, so the UTC weekday matches the ET day.
    return 3 if datetime.now(timezone.utc).weekday() == 0 else 1


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


def from_google_news(query, days=1):
    q = urllib.parse.quote(f"{query} when:{days}d")
    url = f"https://news.google.com/rss/search?q={q}&hl=en-US&gl=US&ceid=US:en"
    return from_rss(f"Google News: {query}", url)


_AJ_HREF_RE = re.compile(r'href="(/news/(?:liveblog/)?\d{4}/\d{1,2}/\d{1,2}/[^"#?]+)"')


def from_aljazeera(source_name, page_url):
    """Scrape an Al Jazeera section/live-blog hub for canonical article links.

    Al Jazeera blocks its RSS to scripts and the plain feed is thin, but its article URLs
    follow a stable /news/[liveblog/]YYYY/M/D/slug scheme, so we pull those directly. The
    slug carries enough text for relevance filtering and for the model to cluster on."""
    out = []
    try:
        html = _fetch(page_url).decode("utf-8", "ignore")
    except Exception as e:
        print(f"  [aje] {source_name} ERR: {e!r}")
        return out
    seen = set()
    for m in _AJ_HREF_RE.finditer(html):
        path = m.group(1)
        url = "https://www.aljazeera.com" + path
        if url in seen:
            continue
        seen.add(url)
        slug = path.rstrip("/").split("/")[-1]
        title = re.sub(r"\s+", " ", slug.replace("-", " ")).strip().capitalize()
        if not _is_relevant(title):
            continue
        out.append({
            "source": "Al Jazeera",
            "collector": source_name,
            "title": title,
            "url": url,
            "summary": "",
            "published": "",
        })
    print(f"  [aje] {source_name}: {len(out)} items")
    return out


def from_manual():
    """Editor-supplied items no scraper reaches: X / Truth Social / YouTube links.

    Reads data/manual.json (a standing file) and data/manual_<date>.json (today only).
    Each entry: {"source": "...", "title": "...", "url": "..."}. This is the cheap bridge
    for primary social sources (CENTCOM, UKMTO, IDF, Trump) until a paid API is added."""
    out = []
    date_str = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    for fname in ("manual.json", f"manual_{date_str}.json"):
        path = DATA_DIR / fname
        if not path.exists():
            continue
        try:
            entries = json.loads(path.read_text(encoding="utf-8"))
        except Exception as e:
            print(f"  [manual] {fname} ERR: {e!r}")
            continue
        for e in entries:
            if not (e.get("title") and e.get("url")):
                continue
            out.append({
                "source": e.get("source") or "Manual",
                "collector": "Manual",
                "title": _clean(e["title"]),
                "url": e["url"].strip(),
                "summary": _clean(e.get("summary", "")),
                "published": e.get("published", ""),
            })
    if out:
        print(f"  [manual]: {len(out)} items")
    return out


def from_gdelt(query, days=1, retries=3):
    q = urllib.parse.quote(query)
    url = (f"https://api.gdeltproject.org/api/v2/doc/doc?query={q}"
           f"&mode=ArtList&maxrecords=75&format=json&timespan={days * 24}h")
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
    days = _lookback_days()
    window = "3-day weekend window (Monday)" if days == 3 else f"{days}-day window"
    print(f"Collecting Iran War Update items for {date_str} (UTC) — {window}")

    items = []
    print("Google News queries:")
    for q in GOOGLE_NEWS_QUERIES:
        items += from_google_news(q, days=days)
    print("Al Jazeera:")
    for name, url in ALJAZEERA_PAGES:
        items += from_aljazeera(name, url)
    print("Direct feeds:")
    for name, url in DIRECT_FEEDS:
        items += from_rss(name, url, filter_relevant=True)
    print("GDELT:")
    items += from_gdelt(GDELT_QUERY, days=days)
    print("Social (X + Truth Social):")
    items += social.collect_social(days=days)
    manual = from_manual()
    if manual:
        print("Manual injection:")
        items += manual

    # Cross-source dedupe by loose title key. On a collision, keep the stronger source
    # (prestige / canonical publisher) over a weaker one (e.g. a Google News redirect).
    best = {}
    order = []
    for it in items:
        k = _norm_key(it["title"])
        if not k:
            continue
        if k not in best:
            best[k] = it
            order.append(k)
        else:
            incumbent = best[k]
            challenger_better = (
                (_is_prestige(it) and not _is_prestige(incumbent)) or
                (not resolve.is_gnews(it["url"]) and resolve.is_gnews(incumbent["url"]))
            )
            if challenger_better:
                best[k] = it
    deduped = [best[k] for k in order]
    print(f"\n{len(items)} raw -> {len(deduped)} after dedupe")

    # Canonicalize Google News redirect links to real publisher URLs so the model can copy
    # them accurately (fixes SOURCE-OR-SKIP drops) and the brief carries clean links.
    deduped = resolve.resolve_items(deduped)

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
