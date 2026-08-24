"""
fulltext.py — Iran War Update, best-effort article body fetcher

The model was only ever shown each item's title plus a thin RSS blurb, so bullets rarely got
past the headline. This fetches real article text for the top items and appends it to their
`summary`, giving the formatter grounded material for sub-bullets (quotes, figures, context)
— the model may still use only what's in that text, so no fabrication.

Design notes (why the first version only enriched ~1 in 6):
  - It fetched Google News *redirect* URLs, which return an interstitial, not article text.
    We now fetch ONLY canonical URLs (skip anything resolve.is_gnews flags).
  - It skipped paywalled outlets entirely. We now still read their <meta> / og:description,
    which sits before the wall, so even WSJ/NYT/Haaretz contribute a sentence of detail.
  - It fetched one URL at a time with a short timeout. We now fetch in parallel, so we can
    cover many more items in the same wall-clock time.

Best-effort: a fetch failure or a bare page just leaves the existing summary. Bodies are
cached in the archive so re-runs and the weekly job don't re-fetch. Disable with FULLTEXT=0.

Stdlib only.
"""

import concurrent.futures as cf
import os
import re
import sqlite3
import urllib.request

import collect   # reuse UA, _clean, _is_prestige, DB_PATH
import resolve   # is_gnews — skip redirect URLs

ENABLED = os.environ.get("FULLTEXT", "1") not in ("0", "false", "False", "")
MAX_ITEMS = 150       # cap fetches per run (now parallel, so this is affordable)
WORKERS = 8
BODY_CHARS = 1200     # chars of extracted text to keep per article
TIMEOUT = 5

# Outlets whose article bodies are paywalled -> take only their meta/og description (which
# sits before the wall), never the (subscribe-wall) body.
PAYWALLED = [
    "wsj.com", "nytimes.com", "haaretz.com", "washingtonpost.com", "ft.com",
    "economist.com", "thetimes.co.uk", "bloomberg.com",
]

_SCRIPT_RE = re.compile(r"<(script|style|noscript)[^>]*>.*?</\1>", re.DOTALL | re.IGNORECASE)
_REGION_RE = re.compile(r"<(article|main)[^>]*>(.*?)</\1>", re.DOTALL | re.IGNORECASE)
_P_RE = re.compile(r"<p[^>]*>(.*?)</p>", re.DOTALL | re.IGNORECASE)
_TAG_RE = re.compile(r"<[^>]+>")
# <meta ... (name|property)="[og:]description" ... content="..."> in either attribute order
_META_A = re.compile(
    r'<meta[^>]+?(?:name|property)=["\'](?:og:)?description["\'][^>]+?content=["\']([^"\']+)["\']',
    re.IGNORECASE)
_META_B = re.compile(
    r'<meta[^>]+?content=["\']([^"\']+)["\'][^>]+?(?:name|property)=["\'](?:og:)?description["\']',
    re.IGNORECASE)


def _is_paywalled(url):
    u = (url or "").lower()
    return any(p in u for p in PAYWALLED)


def extract_meta(html):
    """The page's meta/og description (one or two sentences), or ''."""
    for rx in (_META_A, _META_B):
        m = rx.search(html or "")
        if m:
            return collect._clean(m.group(1))
    return ""


def extract_body(html):
    """Readable paragraph text from an article page (best-effort)."""
    if not html:
        return ""
    html = _SCRIPT_RE.sub(" ", html)
    m = _REGION_RE.search(html)          # prefer the <article>/<main> region if present
    region = m.group(2) if m else html
    paras = [collect._clean(_TAG_RE.sub(" ", pm.group(1))) for pm in _P_RE.finditer(region)]
    return " ".join(p for p in paras if len(p) >= 40)[:BODY_CHARS].strip()


def extract(html, want_body=True):
    """Meta description as a floor, plus the body when allowed."""
    desc = extract_meta(html)
    body = extract_body(html) if want_body else ""
    combined = f"{desc} {body}".strip() if desc else body
    return combined[:BODY_CHARS].strip()


def _fetch(url, want_body, timeout=TIMEOUT):
    try:
        req = urllib.request.Request(url, headers=collect.UA)
        html = urllib.request.urlopen(req, timeout=timeout).read().decode("utf-8", "ignore")
        return extract(html, want_body)
    except Exception:
        return ""


def _rank(it):
    # prefer prestige outlets, then items with the least existing text (they need body most)
    return (collect._is_prestige(it), -len(it.get("summary") or ""))


def _apply(it, body):
    base = it.get("summary") or ""
    it["summary"] = (f"{base} {body}".strip() if base else body)[:1500]


def enrich(items, limit=MAX_ITEMS):
    """Append fetched article text into each item's `summary`, in place. Returns items."""
    if not ENABLED:
        print("  [fulltext] disabled (FULLTEXT=0)")
        return items
    con = sqlite3.connect(collect.DB_PATH)
    con.execute("CREATE TABLE IF NOT EXISTS fulltext (url TEXT PRIMARY KEY, body TEXT)")
    con.commit()

    # Only canonical URLs — fetching a Google News redirect yields an interstitial, not text.
    cands = [it for it in items
             if it.get("url") and not resolve.is_gnews(it["url"])]
    cands.sort(key=_rank, reverse=True)
    cands = cands[:limit]

    todo = []
    for it in cands:
        row = con.execute("SELECT body FROM fulltext WHERE url=?", (it["url"],)).fetchone()
        if row is None:
            todo.append(it)
        elif row[0]:
            _apply(it, row[0])

    fetched = {}
    if todo:
        with cf.ThreadPoolExecutor(max_workers=WORKERS) as ex:
            futs = {ex.submit(_fetch, it["url"], not _is_paywalled(it["url"])): it
                    for it in todo}
            for fut in cf.as_completed(futs):
                url = futs[fut]["url"]
                try:
                    fetched[url] = fut.result() or ""
                except Exception:
                    fetched[url] = ""
        for it in todo:
            body = fetched.get(it["url"], "")
            con.execute("INSERT OR REPLACE INTO fulltext(url, body) VALUES (?,?)",
                        (it["url"], body))
            if body:
                _apply(it, body)
        con.commit()
    con.close()

    enriched = sum(1 for it in cands if (it.get("summary") or "").strip())
    print(f"  [fulltext]: enriched {enriched}/{len(cands)} canonical items "
          f"({len(cands) - len(todo)} cached, {len(todo)} fetched)")
    return items


if __name__ == "__main__":
    html = (
        '<html><head>'
        '<meta property="og:description" content="Iran tied any reopening of the Strait of '
        'Hormuz to U.S. concessions, its foreign ministry said.">'
        '</head><body><nav><p>Home</p></nav>'
        '<article>'
        '<p>Iran said on Monday that it would reopen the Strait of Hormuz only once the '
        'United States met a set of conditions, according to the foreign ministry.</p>'
        '<p>Short.</p>'
        '<p>A second substantial paragraph with more than forty characters of real text '
        'so the extractor keeps it as body content.</p>'
        '</article></body></html>'
    )
    assert extract_meta(html).startswith("Iran tied any reopening"), extract_meta(html)
    body = extract_body(html)
    assert "Iran said on Monday" in body and "Home" not in body and "Short." not in body, body
    both = extract(html, want_body=True)
    assert both.startswith("Iran tied any reopening") and "Iran said on Monday" in both
    # paywalled path: meta only, no body
    meta_only = extract(html, want_body=False)
    assert "Iran tied any reopening" in meta_only and "second substantial" not in meta_only
    print(both)
    print("\nfulltext.py self-test passed")
