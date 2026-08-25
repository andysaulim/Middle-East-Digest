"""
social.py — Iran War Update, free social ingestion (X + Truth Social)

The human tracker leans on primary social posts the RSS/Google sources never carry:
CENTCOM, UKMTO, and the IDF on X, maritime trackers (Windward, MarineTraffic), and Trump
on Truth Social. v2 handled these only through the manual injection file. This module pulls
them automatically from free, public, no-account endpoints:

  - Truth Social is a Mastodon fork. Its Mastodon-compatible API returns clean JSON, and
    unauthenticated viewing is still allowed for a few prominent accounts — Trump among
    them — so his feed needs no login:
        GET /api/v1/accounts/lookup?acct=<handle>   -> the account id
        GET /api/v1/accounts/<id>/statuses          -> recent posts

  - X (Twitter) has no free API, but the syndication endpoint that powers embedded profile
    timelines returns a public account's recent tweets with no auth:
        GET https://syndication.twimg.com/srv/timeline-profile/screen-name/<handle>
    The tweets live in the page's __NEXT_DATA__ JSON blob.

Both are UNSUPPORTED endpoints and can change or (for Truth Social, behind Cloudflare)
return 403 from a datacenter IP. Every fetch is best-effort: on any failure the collector
logs and returns [], and the manual injection file (collect.from_manual) remains the
fallback. If these prove unreliable from GitHub Actions, a cheap paid-per-use scraper drops
into the same seam without a redesign. Disable entirely with SOCIAL_FEEDS=0.

Stdlib only.
"""

import json
import os
import re
import urllib.parse
import urllib.request
from datetime import datetime, timedelta, timezone

import collect  # reuse _clean, _is_relevant, and the browser UA

ENABLED = os.environ.get("SOCIAL_FEEDS", "1") not in ("0", "false", "False", "")

# --- Watchlist. EDIT ME. -----------------------------------------------------
# X handles without the @, from the CSIS input spec. The pull is best-effort: an unknown or
# renamed handle simply returns nothing, so a wrong guess is harmless. Handles marked
# "(verify)" are best-known guesses that should be confirmed against x.com.
X_HANDLES = [
    # U.S. government / officials
    "CENTCOM",            # U.S. Central Command (checked daily)
    "SecRubio",           # Marco Rubio, Secretary of State (also @marcorubio)
    "VP",                 # J.D. Vance, Vice President (also @JDVance)
    "SenSchumer",         # Chuck Schumer
    "GovMikeHuckabee",    # Mike Huckabee, U.S. Ambassador to Israel
    "jaredkushner",       # Jared Kushner (verify; often inactive)
    "SecretaryWright",    # Chris Wright, U.S. Energy Secretary (cited in the human brief)
    "USEmbMuscat",        # U.S. Embassy Muscat (Oman track)
    "MarkWarner",         # Sen. Mark Warner
    # (Massad Boulos and Steve Witkoff have no reliable public X account -> manual file)
    # Gulf / Arab foreign ministries and officials
    "MofaQatar_EN",       # Qatar MoFA, English (verify)
    "mofauae",            # UAE MoFA (verify)
    "AnwarGargash",       # Anwar Gargash, UAE presidential diplomatic adviser
    "KSAmofaEN",          # Saudi Arabia MoFA, English (verify)
    "bahdiplomatic",      # Bahrain MoFA (verify)
    "KuwaitMFA",          # Kuwait MoFA (verify)
    "ForeignMinistry",    # Jordan MoFA (verify)
    "iraqimofa",          # Iraq MoFA (verify)
    "FMofOman",           # Oman MoFA (verify)
    "badralbusaidi",      # Badr Albusaidi, Oman Foreign Minister (verify)
    "PakPMO",             # Pakistan PM Office (verify)
    "Nechirvan_Barzani",  # Nechirvan Barzani, KRG President (verify)
    "modgovksa",          # Saudi Ministry of Defense (cited in the human brief)
    "MFA_China",          # Chinese Foreign Ministry spokesperson
    # Lebanon
    "LBpresidency",       # Lebanese Presidency (verify)
    "nawafsalam",         # Nawaf Salam, Lebanese PM (verify)
    # Israel
    "IsraeliPM",          # Israel Prime Minister's Office
    "Israel_katz",        # Israel Katz
    "bezalelsm",          # Bezalel Smotrich (verify)
    "itamarbengvir",      # Itamar Ben Gvir (verify)
    "IDF",                # Israel Defense Forces
    # Iran
    "drpezeshkian",       # Masoud Pezeshkian (verify)
    "mb_ghalibaf",        # Mohammad Bagher Ghalibaf (as cited in the human brief)
    "araghchi",           # Abbas Araghchi (verify)
    "ir_rezaee",          # Mohsen Rezaee (cited in the human brief)
    # Maritime / shipping data
    "UK_MTO",             # UK Maritime Trade Operations (as cited in the human brief)
    "WindwardAI",         # maritime-domain analytics
    "MarineTraffic",      # vessel tracking
    "Kpler",              # commodity and vessel-flow data
]
# Truth Social accounts without the @. Unauthenticated pull works for allowed accounts
# (Trump, Vance); others would need a logged-in token and are better left to the manual file.
TRUTH_SOCIAL_ACCOUNTS = [
    "realDonaldTrump",
]

_TS_BASE = "https://truthsocial.com/api/v1"
_X_TIMELINE = "https://syndication.twimg.com/srv/timeline-profile/screen-name/{}"
_NEXT_DATA_RE = re.compile(
    r'<script id="__NEXT_DATA__" type="application/json">(.*?)</script>', re.DOTALL)


def _get(url, timeout=20):
    req = urllib.request.Request(url, headers=collect.UA)
    return urllib.request.urlopen(req, timeout=timeout).read()


def _cutoff(days, now):
    return now - timedelta(days=days)


# --- Truth Social ---------------------------------------------------------

def _parse_ts_time(s):
    """Truth Social created_at is ISO 8601 (e.g. 2026-08-05T14:23:00.000Z)."""
    try:
        return datetime.fromisoformat((s or "").replace("Z", "+00:00"))
    except ValueError:
        return None


def _parse_truth_statuses(statuses, account, days, now):
    """Pure parser: Mastodon status JSON -> our records, windowed and keyword-filtered."""
    out = []
    for st in statuses or []:
        text = collect._clean(st.get("content"))
        url = (st.get("url") or "").strip()
        if not (text and url):
            continue
        when = _parse_ts_time(st.get("created_at"))
        if when and when < _cutoff(days, now):
            continue
        if not collect._is_relevant(text):
            continue
        out.append({
            "source": f"Truth Social (@{account})",
            "collector": "Truth Social",
            "title": text[:280],
            "url": url,
            "summary": "",
            "published": st.get("created_at", ""),
        })
    return out


def from_truth_social(accounts=None, days=1, now=None):
    accounts = TRUTH_SOCIAL_ACCOUNTS if accounts is None else accounts
    now = now or datetime.now(timezone.utc)
    out = []
    for acct in accounts:
        try:
            look = json.loads(_get(f"{_TS_BASE}/accounts/lookup?acct={urllib.parse.quote(acct)}"))
            acct_id = look.get("id")
            if not acct_id:
                print(f"  [truth] @{acct}: not found")
                continue
            statuses = json.loads(_get(
                f"{_TS_BASE}/accounts/{acct_id}/statuses?exclude_replies=true&limit=20"))
            out += _parse_truth_statuses(statuses, acct, days, now)
        except Exception as e:
            print(f"  [truth] @{acct} ERR: {e!r}")
    if out:
        print(f"  [truth]: {len(out)} items")
    return out


# --- X (syndication) ------------------------------------------------------

def _parse_x_time(s):
    """X created_at is like 'Wed Aug 05 14:23:00 +0000 2026'."""
    try:
        return datetime.strptime(s, "%a %b %d %H:%M:%S %z %Y")
    except (ValueError, TypeError):
        return None


def _walk_tweets(node, found):
    """Recursively collect tweet dicts (have id_str + text/full_text + created_at)."""
    if isinstance(node, dict):
        if node.get("id_str") and (node.get("full_text") or node.get("text")):
            found.append(node)
        for v in node.values():
            _walk_tweets(v, found)
    elif isinstance(node, list):
        for v in node:
            _walk_tweets(v, found)


def _parse_x_timeline(html, handle, days, now):
    """Pure parser: syndication timeline HTML -> our records, windowed + keyword-filtered."""
    m = _NEXT_DATA_RE.search(html or "")
    if not m:
        return []
    try:
        data = json.loads(m.group(1))
    except ValueError:
        return []
    tweets, seen, out = [], set(), []
    _walk_tweets(data, tweets)
    for tw in tweets:
        tid = tw.get("id_str")
        if tid in seen:
            continue
        seen.add(tid)
        text = collect._clean(tw.get("full_text") or tw.get("text"))
        if not text:
            continue
        when = _parse_x_time(tw.get("created_at"))
        if when and when < _cutoff(days, now):
            continue
        if not collect._is_relevant(text):
            continue
        out.append({
            "source": f"@{handle} (X)",
            "collector": "X",
            "title": text[:280],
            "url": f"https://x.com/{handle}/status/{tid}",
            "summary": "",
            "published": tw.get("created_at", ""),
        })
    return out


def from_x_syndication(handles=None, days=1, now=None):
    handles = X_HANDLES if handles is None else handles
    now = now or datetime.now(timezone.utc)
    out = []
    for h in handles:
        try:
            # short timeout: X blocks datacenter IPs, so these usually hang; don't waste the run
            html = _get(_X_TIMELINE.format(urllib.parse.quote(h)), timeout=6).decode("utf-8", "ignore")
            out += _parse_x_timeline(html, h, days, now)
        except Exception as e:
            print(f"  [x] @{h} ERR: {e!r}")
    if out:
        print(f"  [x]: {len(out)} items (free syndication)")
    return out


# --- X (paid scraper) -----------------------------------------------------
# X killed its free API and blocks datacenter IPs, so the syndication pull above returns
# nothing from GitHub Actions. A cheap per-use scraper (default: twitterapi.io, ~$0.15 per
# 1,000 tweets) reliably pulls each official's recent posts WITH their text. Set X_SCRAPER_KEY
# to enable it; it then replaces the free pull. X_SCRAPER_BASE overrides the vendor endpoint.

_SCRAPER_BASE = os.environ.get("X_SCRAPER_BASE", "https://api.twitterapi.io")


def _parse_scraper_time(s):
    dt = _parse_x_time(s)                      # Twitter format (Tue Aug 25 12:00:00 +0000 2026)
    if dt:
        return dt
    try:
        return datetime.fromisoformat((s or "").replace("Z", "+00:00"))   # ISO 8601
    except (ValueError, TypeError):
        return None


def _walk_x_objs(node, found):
    """Recursively collect tweet-like dicts (a text field + an id field), schema-agnostic."""
    if isinstance(node, dict):
        if (node.get("text") or node.get("full_text")) and \
           (node.get("id") or node.get("id_str") or node.get("tweet_id")):
            found.append(node)
        for v in node.values():
            _walk_x_objs(v, found)
    elif isinstance(node, list):
        for v in node:
            _walk_x_objs(v, found)


def _parse_scraper(data, handle, days, now):
    """Vendor JSON -> our records (windowed + keyword-filtered). The tweet text becomes both
    the title and the summary, so the model can quote it."""
    objs, out, seen = [], [], set()
    _walk_x_objs(data, objs)
    for tw in objs:
        tid = str(tw.get("id") or tw.get("id_str") or tw.get("tweet_id") or "")
        if not tid or tid in seen:
            continue
        seen.add(tid)
        text = collect._clean(tw.get("text") or tw.get("full_text"))
        if not text:
            continue
        created = tw.get("createdAt") or tw.get("created_at") or ""
        when = _parse_scraper_time(created)
        if when and when < _cutoff(days, now):
            continue
        if not collect._is_relevant(text):
            continue
        url = (tw.get("url") or f"https://x.com/{handle}/status/{tid}").strip()
        out.append({
            "source": f"@{handle} (X)", "collector": "X",
            "title": text[:280], "url": url, "summary": text[:2000], "published": created,
        })
    return out


def from_x_scraper(handles=None, days=1, now=None):
    key = os.environ.get("X_SCRAPER_KEY")
    if not key:
        print("  [x] no X_SCRAPER_KEY; skipping paid X scraper")
        return []
    handles = X_HANDLES if handles is None else handles
    now = now or datetime.now(timezone.utc)
    out = []
    for h in handles:
        try:
            url = f"{_SCRAPER_BASE}/twitter/user/last_tweets?userName={urllib.parse.quote(h)}"
            req = urllib.request.Request(url, headers={"X-API-Key": key, "Accept": "application/json"})
            data = json.loads(urllib.request.urlopen(req, timeout=15).read())
            out += _parse_scraper(data, h, days, now)
        except Exception as e:
            print(f"  [x] @{h} ERR: {e!r}")
    print(f"  [x]: {len(out)} items (paid scraper, {len(handles)} accounts)")
    return out


# --- Combined -------------------------------------------------------------

def collect_social(days=1):
    """Truth Social + X, gated by SOCIAL_FEEDS. Uses the paid X scraper when X_SCRAPER_KEY is
    set (reliable, with text), else the free syndication pull (usually empty from CI)."""
    if not ENABLED:
        print("  [social] disabled (SOCIAL_FEEDS=0)")
        return []
    x = from_x_scraper(days=days) if os.environ.get("X_SCRAPER_KEY") else from_x_syndication(days=days)
    return from_truth_social(days=days) + x


# --- self-test (offline fixtures; no network) -----------------------------
if __name__ == "__main__":
    now = datetime(2026, 8, 10, 12, 0, tzinfo=timezone.utc)

    ts_fixture = [
        {"content": "<p>Iran talks are continuing, big progress on Hormuz.</p>",
         "url": "https://truthsocial.com/@realDonaldTrump/111", "created_at": "2026-08-09T10:00:00.000Z"},
        {"content": "<p>Unrelated domestic post about the economy.</p>",
         "url": "https://truthsocial.com/@realDonaldTrump/112", "created_at": "2026-08-09T11:00:00.000Z"},
        {"content": "<p>Old Iran post from last month.</p>",
         "url": "https://truthsocial.com/@realDonaldTrump/110", "created_at": "2026-07-01T10:00:00.000Z"},
    ]
    ts = _parse_truth_statuses(ts_fixture, "realDonaldTrump", days=3, now=now)
    assert len(ts) == 1, ts                              # keyword + window filter
    assert "Hormuz" in ts[0]["title"] and ts[0]["url"].endswith("/111")
    assert ts[0]["source"] == "Truth Social (@realDonaldTrump)"

    x_next = {"props": {"pageProps": {"timeline": {"entries": [
        {"content": {"tweet": {"id_str": "999", "full_text": "IDF struck Hezbollah targets in Lebanon.",
                               "created_at": "Sat Aug 09 08:00:00 +0000 2026"}}},
        {"content": {"tweet": {"id_str": "998", "full_text": "Happy national donut day!",
                               "created_at": "Sat Aug 09 09:00:00 +0000 2026"}}},
        {"content": {"tweet": {"id_str": "997", "full_text": "Old Yemen strike note.",
                               "created_at": "Fri Jul 01 09:00:00 +0000 2026"}}},
    ]}}}}
    html = ('<html><script id="__NEXT_DATA__" type="application/json">'
            + json.dumps(x_next) + "</script></html>")
    xs = _parse_x_timeline(html, "IDF", days=3, now=now)
    assert len(xs) == 1, xs                              # keyword + window filter
    assert xs[0]["url"] == "https://x.com/IDF/status/999"
    assert xs[0]["source"] == "@IDF (X)" and xs[0]["collector"] == "X"

    # Malformed input degrades to empty, never raises.
    assert _parse_x_timeline("<html>no next data</html>", "IDF", 3, now) == []
    assert _parse_truth_statuses([], "x", 1, now) == []

    # Paid-scraper parser: schema-agnostic (tweets nested under data), text -> summary.
    scraper_payload = {"status": "success", "data": {"tweets": [
        {"id": "555", "text": "CENTCOM redirected 70 vessels and disabled 3 to enforce the blockade on Iran.",
         "createdAt": "Sat Aug 09 08:00:00 +0000 2026",
         "url": "https://x.com/CENTCOM/status/555"},
        {"id": "556", "text": "Team dinner was great tonight.",
         "createdAt": "Sat Aug 09 09:00:00 +0000 2026"},
        {"id_str": "557", "full_text": "Old Hormuz note.",
         "created_at": "2026-07-01T09:00:00Z"},
    ]}}
    sc = _parse_scraper(scraper_payload, "CENTCOM", days=3, now=now)
    assert len(sc) == 1, sc                              # off-topic + stale dropped
    assert sc[0]["url"] == "https://x.com/CENTCOM/status/555"
    assert "70 vessels" in sc[0]["summary"] and sc[0]["collector"] == "X"
    # id fallback builds the permalink when the vendor omits url
    sc2 = _parse_scraper({"tweets": [{"id": "900", "text": "IDF struck targets in Lebanon.",
                                      "createdAt": "Sat Aug 09 08:00:00 +0000 2026"}]},
                         "IDF", days=3, now=now)
    assert sc2 and sc2[0]["url"] == "https://x.com/IDF/status/900", sc2

    print("social.py self-test passed")
