"""
collect.py — Iran War Update, live collector (Phase 1)

Pulls the day's Iran-war items from free sources:
  1. Google News RSS search queries (the main relevance engine)
  2. Al Jazeera Middle East section + the Iran-war LIVEBLOG (the human tracker's backbone,
     ~77% of its links): article links plus each liveblog update's own text and deep link
  3. Direct outlet RSS feeds (Times of Israel, Al Arabiya), keyword-filtered
  4. GDELT DOC 2.0 API as an event backbone
  5. Social feeds (X + Truth Social) via social.py
  6. Subscriber-only newsletters read from the Gmail inbox over IMAP (newsletters.py)
  7. A manual injection file for items no scraper reaches, dropped in by hand

Normalizes everything to a common record, drops stale items (published outside the lookback
window — see _filter_stale), dedupes (preferring prestige / canonical sources), canonicalizes
Google News redirect links to real publisher URLs (resolve.py), enriches the top items with
full article text (fulltext.py) so the brief can go beyond the headline, and writes both a
dated JSON file (for the digest step) and a SQLite archive (the queryable corpus).

Lookback window (calendar days, America/New_York): the brief carries only items published
on the brief's own ET date on Tue-Fri (a brief dated 8/25 is Tuesday-only). Monday reaches
back to Saturday 00:00 ET so the weekend (Saturday, Sunday, Monday) is not lost, since there
is no weekend brief. Override the span with the LOOKBACK_DAYS env var after a holiday.

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
import hashlib
from datetime import datetime, timezone, timedelta
from email.utils import parsedate_to_datetime
from pathlib import Path

try:                                     # ET calendar-day alignment (see _et_day_start)
    from zoneinfo import ZoneInfo
    _ET = ZoneInfo("America/New_York")
except Exception:                        # no tz database on the host -> assume EDT (UTC-4)
    _ET = timezone(timedelta(hours=-4))

import resolve
import social
import fulltext
import newsletters

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
    # tier one
    "reuters", "al jazeera", "axios", "wall street journal", "wsj", "new york times", "nyt",
    # tier two
    "the national", "l'orient", "lorient", "times of israel", "haaretz",
    "treasury", "state department", "state.gov",
    # tier three
    "washington post", "asharq", "aawsat", "sana", "al-monitor", "al monitor",
    # other strong wires kept for dedupe preference
    "associated press", "ap news", "financial times", "bloomberg", "the economist",
    "bbc", "guardian",
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
    # Al Jazeera Iran-war liveblog (discovery target — resolved to the canonical AJ URL):
    "Iran war live blog Al Jazeera",
    # Maritime / shipping data (Kpler, MarineTraffic, Bab el-Mandeb):
    "Kpler Iran oil exports Hormuz blockade",
    "MarineTraffic Strait of Hormuz transit vessels",
    "Bab el-Mandeb shipping Houthi Red Sea disruption",
    # Tier-1/2/3 outlets, site-scoped so each named source is represented (the CSIS input
    # spec's source list). Google News still lists paywalled outlets; resolve.py canonicalizes.
    "Iran war site:aljazeera.com",
    "Iran OR Hormuz site:reuters.com",
    "Iran OR Israel site:axios.com",
    "Iran OR Israel site:wsj.com",
    "Iran OR Israel OR Lebanon site:nytimes.com",
    "Iran OR Lebanon OR Gulf site:thenationalnews.com",
    "Lebanon OR Israel OR Iran site:lorientlejour.com",
    "Iran OR Hezbollah OR Houthi site:timesofisrael.com",
    "Iran OR Israel OR Lebanon site:haaretz.com",
    "Iran OR Israel site:washingtonpost.com",
    "Iran OR Gulf site:english.aawsat.com",
    "Iran OR Syria site:sana.sy",
    "Iran OR Gulf site:al-monitor.com",
    "Iran sanctions site:home.treasury.gov",
    "Iran OR Middle East site:state.gov",
]

# Al Jazeera pages scraped for canonical article links (the live blog is under /news/liveblog/).
ALJAZEERA_PAGES = [
    ("Al Jazeera Middle East", "https://www.aljazeera.com/where/middle-east/"),
    ("Al Jazeera News", "https://www.aljazeera.com/news/"),
    ("Al Jazeera Iran", "https://www.aljazeera.com/where/iran/"),
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
    "pezeshkian", "oman", "red sea", "bab el mandeb", "bab-el-mandeb", "nuclear",
    "blockade", "netanyahu", "unifil", "centcom", "iraq", "syria", "jordan", "egypt",
    "suez", "caspian", "gulf", "khamenei", "nasrallah", "beirut",
    # countries added by the CSIS input spec
    "bahrain", "kuwait", "qatar", "doha", "uae", "emirates", "abu dhabi", "dubai",
    "pakistan", "turkey", "turkish", "ghalibaf", "katz", "smotrich", "ben gvir",
    # maritime data providers
    "kpler", "marinetraffic",
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


_TRACKING_PARAMS = {
    "ref", "ref_src", "ref_url", "fbclid", "gclid", "mc_cid", "mc_eid", "igshid",
    "email", "cmpid", "smid", "spm", "src", "s",
}


def _norm_url(url):
    """Canonical form of a URL for dedupe: scheme/host lowered, trailing slash and *tracking*
    query params dropped, fragment dropped. Crucially, CONTENT query params are kept — an Al
    Jazeera liveblog update is identified by its ?update=NNNN param, so stripping the whole
    query would collapse every update of one liveblog into a single key (and cross-day
    suppression would then drop all but the first). Only utm_*/ref/email-style trackers are
    removed. A liveblog update's #anchor is also preserved, for updates keyed that way."""
    u = (url or "").strip()
    if not u:
        return ""
    frag = ""
    if "#" in u:
        u, frag = u.split("#", 1)
    base, _, query = u.partition("?")
    base = re.sub(r"^https?://", "", base, flags=re.I).lower().rstrip("/")
    kept = []
    for part in query.split("&"):
        if not part:
            continue
        key = part.split("=", 1)[0].lower()
        if key.startswith("utm_") or key in _TRACKING_PARAMS:
            continue
        kept.append(part)
    if kept:
        base = f"{base}?{'&'.join(sorted(kept))}"
    # Keep a liveblog update's anchor (…#…) as part of the key; drop other fragments.
    if frag and "liveblog" in base:
        base = f"{base}#{frag.lower()}"
    return base


_STOPWORDS = {
    "the", "a", "an", "of", "to", "in", "on", "for", "and", "or", "as", "at", "by",
    "with", "from", "is", "are", "was", "were", "be", "been", "after", "over", "amid",
    "says", "say", "said", "reports", "report", "reported", "new", "its", "his", "her",
    "their", "it", "he", "she", "they", "this", "that", "into", "than", "will", "has",
    "have", "had", "up", "out", "off", "about", "us", "u.s.", "iran", "iranian",
}


def _title_tokens(title):
    """Significant lowercase word tokens of a title (stopwords and short words dropped),
    for measuring how much two headlines overlap."""
    words = re.findall(r"[a-z0-9]+", (title or "").lower())
    return {w for w in words if len(w) > 2 and w not in _STOPWORDS}


def _tok_match(a, b):
    """Two title tokens count as the same word if equal or one is a prefix of the other
    (min length 4), so morphological variants that differ across outlets collapse:
    israel/israeli, south/southern, strike/strikes, position/positions."""
    return a == b or (len(a) >= 4 and len(b) >= 4 and (a.startswith(b) or b.startswith(a)))


def _same_story(a_tokens, b_tokens):
    """True when two headlines describe the same event: enough shared significant tokens
    (prefix-matched, so wording differences don't defeat it) and a high overlap ratio.
    Conservative on purpose so distinct strikes or statements are not merged. 'Iran'/
    'Iranian' are stopwords here so two unrelated Iran items don't collide on that alone."""
    if len(a_tokens) < 3 or len(b_tokens) < 3:
        return False
    shared = sum(1 for a in a_tokens if any(_tok_match(a, b) for b in b_tokens))
    if shared < 4:
        return False
    denom = len(a_tokens) + len(b_tokens) - shared
    return denom > 0 and shared / denom >= 0.55


def _stronger(challenger, incumbent):
    """True when challenger is a better representative of a story than incumbent: a prestige
    outlet over a non-prestige one, or a canonical link over a Google News redirect."""
    return (
        (_is_prestige(challenger) and not _is_prestige(incumbent)) or
        (not resolve.is_gnews(challenger.get("url", "")) and
         resolve.is_gnews(incumbent.get("url", "")))
    )


def _dedupe(items):
    """Collapse duplicate reports of the same event, keeping the strongest source. Three
    passes: exact normalized title, canonical URL, then fuzzy title-token overlap so the same
    story under two differently-worded headlines is caught (the plain title key missed those,
    which is what surfaced as repetition in the brief). Order is otherwise preserved."""
    # Pass 1 — exact normalized title.
    best, order = {}, []
    for it in items:
        k = _norm_key(it.get("title"))
        if not k:
            k = _norm_url(it.get("url"))
        if not k:
            continue
        if k not in best:
            best[k] = it
            order.append(k)
        elif _stronger(it, best[k]):
            best[k] = it
    survivors = [best[k] for k in order]

    # Pass 2 — canonical URL (catches same link with differing titles, and Google News
    # redirects that resolved to the same publisher URL).
    best, order = {}, []
    for it in survivors:
        k = _norm_url(it.get("url")) or _norm_key(it.get("title"))
        if not k:
            continue
        if k not in best:
            best[k] = it
            order.append(k)
        elif _stronger(it, best[k]):
            best[k] = it
    survivors = [best[k] for k in order]

    # Pass 3 — fuzzy title overlap (differently-worded headlines for one event).
    kept, kept_tokens = [], []
    for it in survivors:
        toks = _title_tokens(it.get("title"))
        dup = next((i for i, kt in enumerate(kept_tokens) if _same_story(toks, kt)), None)
        if dup is None:
            kept.append(it)
            kept_tokens.append(toks)
        elif _stronger(it, kept[dup]):
            kept[dup] = it
            kept_tokens[dup] = toks
    return kept


def _drop_seen_before(items, date_str):
    """Suppress items whose canonical URL was already collected on an earlier date, so a
    story (or an unchanged liveblog update) does not reappear in consecutive briefs. Items
    first seen today are kept. Returns (kept, dropped)."""
    try:
        con = sqlite3.connect(DB_PATH)
        rows = con.execute("SELECT url FROM items WHERE collected_date < ?",
                           (date_str,)).fetchall()
        con.close()
    except Exception:
        return items, 0
    seen = {_norm_url(r[0]) for r in rows if r[0]}
    kept, dropped = [], 0
    for it in items:
        if _norm_url(it.get("url")) in seen:
            dropped += 1
        else:
            kept.append(it)
    return kept, dropped


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
    # Monday == 0. The cron runs 13:00 UTC (~9am ET), so the UTC weekday matches the ET day.
    return 3 if datetime.now(timezone.utc).weekday() == 0 else 1


_GDELT_DATE_RE = re.compile(r"^\d{8}T\d{6}Z$")


def _parse_published(s):
    """Parse the date formats the collectors produce into an aware UTC datetime, or None.

    Handles RSS pubDate (RFC 822), GDELT seendate (YYYYMMDDTHHMMSSZ), and ISO 8601
    (including a bare YYYY-MM-DD, treated as midnight UTC). Returns None if unparseable."""
    s = (s or "").strip()
    if not s:
        return None
    if _GDELT_DATE_RE.match(s):
        try:
            return datetime.strptime(s, "%Y%m%dT%H%M%SZ").replace(tzinfo=timezone.utc)
        except ValueError:
            return None
    try:                                     # RFC 822 (Fri, 07 Aug 2026 12:00:00 GMT)
        dt = parsedate_to_datetime(s)
        if dt is not None:
            return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)
    except (TypeError, ValueError, IndexError):
        pass
    try:                                     # ISO 8601, incl. bare date
        dt = datetime.fromisoformat(s.replace("Z", "+00:00"))
        return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)
    except ValueError:
        return None


def _et_day_start(now=None):
    """Midnight (00:00) of the current America/New_York calendar day, as an aware UTC
    datetime. This is the anchor for a same-day window: the ~9am ET send means a brief
    dated D keeps items published from 00:00 ET on D onward."""
    now = now or datetime.now(timezone.utc)
    et = now.astimezone(_ET)
    start_et = et.replace(hour=0, minute=0, second=0, microsecond=0)
    return start_et.astimezone(timezone.utc)


def _window_cutoff(days, now=None):
    """Oldest publish time we keep, aligned to ET calendar-day boundaries rather than a
    rolling clock so a weekday brief is strictly same-day. days=1 -> start of today (ET);
    days=3 (Monday) -> start of Saturday (ET), so the weekend is carried, not a bleed of
    the prior evening. Older items that leak through the collectors are dropped."""
    return _et_day_start(now) - timedelta(days=days - 1)


def _filter_stale(items, cutoff):
    """Drop items whose published date is parseable AND older than cutoff. Items with no
    parseable date are kept (their source is already recency-bounded). Returns (kept, dropped)."""
    kept, dropped = [], 0
    for it in items:
        dt = _parse_published(it.get("published"))
        if dt is not None and dt < cutoff:
            dropped += 1
        else:
            kept.append(it)
    return kept, dropped


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
        # The path carries the publish date (/news/[liveblog/]YYYY/M/D/slug); use it so the
        # date filter and the model can date these accurately.
        dm = re.search(r"/(\d{4})/(\d{1,2})/(\d{1,2})/", path)
        published = (f"{int(dm.group(1)):04d}-{int(dm.group(2)):02d}-{int(dm.group(3)):02d}"
                     "T12:00:00Z") if dm else ""
        out.append({
            "source": "Al Jazeera",
            "collector": source_name,
            "title": title,
            "url": url,
            "summary": "",
            "published": published,
        })
    print(f"  [aje] {source_name}: {len(out)} items")
    return out


def _iter_jsonld(node):
    """Yield every dict inside a parsed JSON-LD blob (handles @graph and lists)."""
    if isinstance(node, dict):
        yield node
        for v in node.values():
            yield from _iter_jsonld(v)
    elif isinstance(node, list):
        for v in node:
            yield from _iter_jsonld(v)


_JSONLD_RE = re.compile(
    r'<script[^>]+type=["\']application/ld\+json["\'][^>]*>(.*?)</script>',
    re.DOTALL | re.IGNORECASE)
_H_SPLIT_RE = re.compile(r"(<h[23][^>]*>.*?</h[23]>)", re.DOTALL | re.IGNORECASE)


def _content_anchor(text):
    """A short, content-derived anchor for a liveblog update that lacks its own deep link.
    Keying the fallback URL on the update's text (not its position on the page) keeps it
    stable across days, so the same update is recognized and suppressed tomorrow instead of
    reappearing under a shifted index."""
    return hashlib.sha1((text or "").encode("utf-8", "ignore")).hexdigest()[:10]


def from_aljazeera_liveblog(page_url):
    """Scrape one Al Jazeera liveblog for its individual updates (heading + text + time).

    The Iran-war liveblog is the human tracker's backbone (~77% of its links). Each update
    carries the quotes and figures the brief needs. Prefer the page's LiveBlogPosting JSON-LD
    (structured: headline, articleBody, datePublished, url per update); fall back to splitting
    the rendered HTML on update headings. Best-effort — returns [] on any failure."""
    try:
        html = _fetch(page_url).decode("utf-8", "ignore")
    except Exception as e:
        print(f"  [aje-live] {page_url} ERR: {e!r}")
        return []

    out, seen, content_seen = [], set(), set()
    jsonld_seen = 0

    # 1) LiveBlogPosting JSON-LD (most reliable). The page was discovered *as* the Iran-war
    #    liveblog, so its updates are on-topic by construction — do NOT re-filter each update
    #    against the Iran keyword list (that was dropping most updates and leaving only one).
    for m in _JSONLD_RE.finditer(html):
        try:
            data = json.loads(m.group(1))
        except ValueError:
            continue
        for node in _iter_jsonld(data):
            updates = node.get("liveBlogUpdate") if isinstance(node, dict) else None
            if not isinstance(updates, list):
                continue
            for up in updates:
                if not isinstance(up, dict):
                    continue
                jsonld_seen += 1
                head = _clean(up.get("headline") or up.get("name"))
                body = _clean(up.get("articleBody") or up.get("description"))
                text = f"{head} {body}".strip()
                if len(text) < 40:                 # skip trivial/procedural updates
                    continue
                anchor = _content_anchor(head + body)
                if anchor in content_seen:         # dedup by content, not by URL
                    continue
                # Each update needs a distinct, stable link. Use the update's own URL when it
                # already distinguishes updates (an ?update= param or a #fragment); otherwise
                # the feed handed us the bare page URL, so append a content anchor so every
                # update keeps its own link instead of collapsing to one.
                raw = (up.get("url") or "").strip()
                if raw and ("update=" in raw or "#" in raw):
                    url = raw
                elif raw:
                    url = f"{raw}#u{anchor}"
                else:
                    url = f"{page_url}#u{anchor}"
                content_seen.add(anchor)
                seen.add(url)
                out.append({
                    "source": "Al Jazeera", "collector": "AJ liveblog",
                    "title": (head or body)[:280], "url": url,
                    "summary": body[:2200], "published": up.get("datePublished", ""),
                })

    # 2) If JSON-LD was thin (or absent), ALSO split the article region on update headings
    #    (h2/h3) and merge — deduped by content anchor against what JSON-LD already captured.
    if len(out) < 5:
        region = html
        rm = re.search(r"<(article|main)[^>]*>(.*?)</\1>", html, re.DOTALL | re.IGNORECASE)
        if rm:
            region = rm.group(2)
        parts = _H_SPLIT_RE.split(region)
        for i in range(1, len(parts) - 1, 2):
            head = _clean(re.sub(r"<[^>]+>", " ", parts[i]))
            body = _clean(re.sub(r"<[^>]+>", " ", parts[i + 1]))
            if not head or len(body) < 60:
                continue
            anchor = _content_anchor(head + body)
            if anchor in content_seen:            # same update already from JSON-LD
                continue
            url = f"{page_url}#u{anchor}"
            if url in seen:
                continue
            seen.add(url)
            content_seen.add(anchor)
            out.append({
                "source": "Al Jazeera", "collector": "AJ liveblog",
                "title": head[:280], "url": url, "summary": body[:2200], "published": "",
            })

    # 3) Last resort: chunk the page's substantial, on-topic paragraphs into pseudo-updates,
    #    so we still capture liveblog content even if its markup is unfamiliar.
    if not out:
        paras = [_clean(re.sub(r"<[^>]+>", " ", p))
                 for p in re.findall(r"<p[^>]*>(.*?)</p>", html, re.DOTALL | re.IGNORECASE)]
        paras = [p for p in paras if len(p) >= 60 and _is_relevant(p)]
        for i in range(0, min(len(paras), 60), 3):
            chunk = " ".join(paras[i:i + 3])
            out.append({
                "source": "Al Jazeera", "collector": "AJ liveblog",
                "title": chunk[:120], "url": f"{page_url}#c{_content_anchor(chunk)}",
                "summary": chunk[:2200], "published": "",
            })

    slug = page_url.rsplit('/', 1)[-1][:40]
    print(f"  [aje-live] {slug}: {len(out)} updates ({jsonld_seen} in JSON-LD)")
    return out


def _discover_liveblogs(items, limit=3):
    """Find the current Al Jazeera Iran-war liveblog URL(s) from several independent sources,
    so discovery does not hinge on any one of them: a manual override env var, canonical
    liveblog links already scraped from AJ hub pages, and Google News results (resolved to
    their real AJ URL). Returns up to `limit` liveblog URLs."""
    found = []

    def add(u):
        if u and "aljazeera.com/news/liveblog/" in u and u not in found:
            found.append(u)

    add((os.environ.get("ALJAZEERA_LIVEBLOG_URL") or "").strip())   # 1) manual override
    for it in items:                                               # 2) hub-scraped canonical
        add(it.get("url", ""))
    for it in items:                                               # 3) Google News -> resolve
        if len(found) >= limit:
            break
        blob = f"{it.get('source', '')} {it.get('collector', '')} {it.get('title', '')}".lower()
        u = it.get("url", "")
        if "jazeera" in blob and ("live" in blob or "iran war" in blob) and resolve.is_gnews(u):
            try:
                add((resolve.resolve_url(u) or "").strip())
            except Exception:
                pass

    print(f"  [aje-live] discovered {len(found)} liveblog URL(s)"
          + (": " + found[0] if found else ""))
    return found[:limit]


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
    print("Newsletters (IMAP + web):")
    items += newsletters.collect_newsletters()
    manual = from_manual()
    if manual:
        print("Manual injection:")
        items += manual

    # Al Jazeera Iran-war liveblog — the human tracker's backbone (~77% of its links).
    # Discover its URL from every source gathered so far, then scrape its per-update text.
    print("Al Jazeera liveblog:")
    for lb in _discover_liveblogs(items):
        items += from_aljazeera_liveblog(lb)

    # Drop stale items: anything published before the ET calendar-day cutoff (same-day on
    # Tue-Fri; back to Saturday on Monday). This is what keeps a brief dated 8/25 Tuesday-only
    # and what let a week-old Treasury item slip in before. Dateless items are kept.
    cutoff = _window_cutoff(days)
    items, dropped = _filter_stale(items, cutoff)
    print(f"Dropped {dropped} stale items (published before {cutoff:%Y-%m-%d %H:%MZ})")

    # Cross-source dedupe (exact title, canonical URL, then fuzzy title overlap), keeping the
    # stronger source on each collision.
    raw = len(items)
    deduped = _dedupe(items)
    print(f"\n{raw} raw -> {len(deduped)} after dedupe")

    # Canonicalize Google News redirect links to real publisher URLs so the model can copy
    # them accurately (fixes SOURCE-OR-SKIP drops) and the brief carries clean links.
    deduped = resolve.resolve_items(deduped)
    # Second dedupe pass: now that redirects are canonical, collapse any that resolved to the
    # same publisher URL.
    deduped = _dedupe(deduped)

    # Cross-day suppression: drop stories (by canonical URL) already carried on an earlier
    # date, so the same item does not repeat in consecutive briefs. Runs before enrich so we
    # don't spend full-text fetches on items we're about to drop.
    deduped, repeats = _drop_seen_before(deduped, date_str)
    print(f"Dropped {repeats} items already seen on an earlier date")

    # Enrich the top items with real article text so the model can write beyond the headline.
    deduped = fulltext.enrich(deduped)

    con = init_db()
    new = archive(con, deduped, date_str)
    con.close()
    print(f"Archived {new} new items to {DB_PATH}")

    out_path = DATA_DIR / f"items_{date_str}.json"
    out_path.write_text(json.dumps(deduped, indent=2, ensure_ascii=False),
                        encoding="utf-8")
    print(f"Wrote {out_path}")
    return out_path


def _selftest():
    """Offline regression tests for the date window and dedupe logic (no network)."""
    # ET calendar-day window: a Tuesday brief keeps Tuesday only; Monday reaches Saturday.
    tue = datetime(2026, 8, 25, 13, 0, tzinfo=timezone.utc)
    assert _window_cutoff(1, now=tue) == datetime(2026, 8, 25, 4, 0, tzinfo=timezone.utc)
    mon = datetime(2026, 8, 24, 13, 0, tzinfo=timezone.utc)
    assert _window_cutoff(3, now=mon) == datetime(2026, 8, 22, 4, 0, tzinfo=timezone.utc)
    cut = _window_cutoff(1, now=tue)
    # Monday-evening ET item (= Tue 03:00 UTC) dropped; Tuesday-morning ET item kept.
    assert _filter_stale(
        [{"title": "x", "url": "http://a",
          "published": "Mon, 24 Aug 2026 23:00:00 -0400"}], cut)[0] == []
    assert len(_filter_stale(
        [{"title": "y", "url": "http://b",
          "published": "Tue, 25 Aug 2026 06:00:00 -0400"}], cut)[0]) == 1

    # Fuzzy dedupe: two differently-worded reports of one event merge, prestige wins,
    # distinct events stay separate.
    d = _dedupe([
        {"title": "Israel strikes Hezbollah positions in south Lebanon overnight",
         "url": "https://news.google.com/rss/articles/AAA",
         "source": "Google News", "collector": "Google News"},
        {"title": "Israeli military strikes Hezbollah positions across southern Lebanon",
         "url": "https://reuters.com/world/mideast/xyz",
         "source": "Reuters", "collector": "RSS"},
        {"title": "Oil tanker seized near Strait of Hormuz",
         "url": "https://apnews.com/tanker", "source": "AP", "collector": "RSS"},
    ])
    assert len(d) == 2 and {x["source"] for x in d} == {"Reuters", "AP"}, d

    # URL normalization keeps liveblog updates distinct — whether keyed by #anchor or by the
    # ?update= content param — while stripping tracking params and non-liveblog fragments.
    assert _norm_url("https://www.aljazeera.com/news/liveblog/2026/8/25/l#u1") != \
        _norm_url("https://www.aljazeera.com/news/liveblog/2026/8/25/l#u2")
    assert _norm_url("https://www.aljazeera.com/news/liveblog/2026/8/24/s?update=4880890") != \
        _norm_url("https://www.aljazeera.com/news/liveblog/2026/8/24/s?update=4880837")
    assert _norm_url("https://x.com/a/status/1?ref_src=twsrc&utm_medium=x#frag") == \
        "x.com/a/status/1"
    print("collect.py self-test passed")


if __name__ == "__main__":
    import sys
    if "--selftest" in sys.argv:
        _selftest()
    else:
        collect()
