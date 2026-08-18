"""
fulltext.py — Iran War Update, best-effort article body fetcher

The model was only ever shown each item's title plus a thin RSS blurb, so bullets rarely got
past the headline. This fetches the real article text for the top items and appends it to
their `summary`, giving the formatter grounded material for sub-bullets (quotes, figures,
context) — the model still may use only what's in that text, so no fabrication.

Best-effort: a fetch failure, a block, or a paywall just leaves the existing summary. Bodies
are cached in the archive so re-runs and the weekly job don't re-fetch. Paywalled outlets are
skipped (their bodies come back as subscribe-wall boilerplate). Disable with FULLTEXT=0.

Stdlib only.
"""

import os
import re
import sqlite3
import urllib.request

import collect  # reuse UA, _clean, _is_prestige, DB_PATH

ENABLED = os.environ.get("FULLTEXT", "1") not in ("0", "false", "False", "")
MAX_ITEMS = 60        # cap fetches per run (sequential, ~adds 1-3 min)
BODY_CHARS = 1200     # chars of body text to keep per article
TIMEOUT = 6

# Outlets whose article bodies are paywalled -> keep the RSS blurb instead of fetching junk.
PAYWALLED = [
    "wsj.com", "nytimes.com", "haaretz.com", "washingtonpost.com", "ft.com",
    "economist.com", "thetimes.co.uk", "bloomberg.com",
]

_SCRIPT_RE = re.compile(r"<(script|style|noscript)[^>]*>.*?</\1>", re.DOTALL | re.IGNORECASE)
_REGION_RE = re.compile(r"<(article|main)[^>]*>(.*?)</\1>", re.DOTALL | re.IGNORECASE)
_P_RE = re.compile(r"<p[^>]*>(.*?)</p>", re.DOTALL | re.IGNORECASE)
_TAG_RE = re.compile(r"<[^>]+>")


def _is_paywalled(url):
    u = (url or "").lower()
    return any(p in u for p in PAYWALLED)


def extract_body(html):
    """Pull readable paragraph text from an article page (best-effort)."""
    if not html:
        return ""
    html = _SCRIPT_RE.sub(" ", html)
    m = _REGION_RE.search(html)          # prefer the <article>/<main> region if present
    region = m.group(2) if m else html
    paras = []
    for pm in _P_RE.finditer(region):
        txt = collect._clean(_TAG_RE.sub(" ", pm.group(1)))
        if len(txt) >= 40:               # skip nav / caption / boilerplate scraps
            paras.append(txt)
    return " ".join(paras)[:BODY_CHARS].strip()


def fetch_body(url, timeout=TIMEOUT):
    try:
        req = urllib.request.Request(url, headers=collect.UA)
        html = urllib.request.urlopen(req, timeout=timeout).read().decode("utf-8", "ignore")
        return extract_body(html)
    except Exception:
        return ""


def _rank(it):
    # prefer prestige outlets, then items with the least existing text (they need body most)
    return (collect._is_prestige(it), -len(it.get("summary") or ""))


def enrich(items, limit=MAX_ITEMS):
    """Append fetched article bodies into each item's `summary`, in place. Returns items."""
    if not ENABLED:
        print("  [fulltext] disabled (FULLTEXT=0)")
        return items
    con = sqlite3.connect(collect.DB_PATH)
    con.execute("CREATE TABLE IF NOT EXISTS fulltext (url TEXT PRIMARY KEY, body TEXT)")
    con.commit()
    candidates = [it for it in items if it.get("url") and not _is_paywalled(it["url"])]
    candidates.sort(key=_rank, reverse=True)
    enriched = 0
    for it in candidates[:limit]:
        url = it["url"]
        row = con.execute("SELECT body FROM fulltext WHERE url=?", (url,)).fetchone()
        if row is None:
            body = fetch_body(url)
            con.execute("INSERT OR REPLACE INTO fulltext(url, body) VALUES (?,?)",
                        (url, body or ""))
            con.commit()
        else:
            body = row[0]
        if body:
            base = it.get("summary") or ""
            it["summary"] = (f"{base} {body}".strip() if base else body)[:1500]
            enriched += 1
    con.close()
    print(f"  [fulltext]: enriched {enriched}/{min(len(candidates), limit)} items")
    return items


if __name__ == "__main__":
    html = (
        "<html><body><nav><p>Home</p></nav>"
        "<article>"
        "<p>Iran said on Monday that it would reopen the Strait of Hormuz only once the "
        "United States met a set of conditions, according to the foreign ministry.</p>"
        "<p>Short.</p>"
        "<p>A second substantial paragraph with more than forty characters of real text "
        "so the extractor keeps it as body content.</p>"
        "</article></body></html>"
    )
    body = extract_body(html)
    assert "Iran said on Monday" in body, body
    assert "Home" not in body, "nav outside <article> should be excluded"
    assert "Short." not in body, "sub-40-char paragraph should be dropped"
    assert "second substantial paragraph" in body
    print(body)
    print("\nfulltext.py self-test passed")
