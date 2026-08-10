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
# X handles without the @. Verify each handle is current before relying on it.
X_HANDLES = [
    "CENTCOM",         # U.S. Central Command
    "IDF",             # Israel Defense Forces
    "UKMTO",           # UK Maritime Trade Operations (Strait of Hormuz advisories)
    "Windward_Ltd",    # maritime-domain analytics
    "MarineTraffic",   # vessel tracking
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
            html = _get(_X_TIMELINE.format(urllib.parse.quote(h))).decode("utf-8", "ignore")
            out += _parse_x_timeline(html, h, days, now)
        except Exception as e:
            print(f"  [x] @{h} ERR: {e!r}")
    if out:
        print(f"  [x]: {len(out)} items")
    return out


# --- Combined -------------------------------------------------------------

def collect_social(days=1):
    """Both feeds, gated by SOCIAL_FEEDS. Returns a combined list (possibly empty)."""
    if not ENABLED:
        print("  [social] disabled (SOCIAL_FEEDS=0)")
        return []
    return from_truth_social(days=days) + from_x_syndication(days=days)


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

    print("social.py self-test passed")
