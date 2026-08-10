"""
congress.py — Iran War Update, "U.S. Congress" section

Iran-related legislative activity (bills, resolutions, sanctions measures) is part of the
U.S. picture the human tracker watches. This module pulls recent bills from the official
Library of Congress API (api.congress.gov), keeps the ones whose title concerns Iran, and
renders a deterministic "U.S. Congress" section appended to the daily brief.

Like the "Dates ahead" and "This day in history" sections, this is rendered directly from
the source (never routed through the model), so the brief can't invent a bill number or a
date. It is best-effort: with no CONGRESS_API_KEY, or on any API error, it returns "" and
the section is simply omitted.

Get a free key instantly at https://api.congress.gov/sign-up/ and set it as CONGRESS_API_KEY.

Scope note: matching is by bill TITLE (Iran / Iranian / Tehran / IRGC / Revolutionary
Guard), so Iran provisions buried inside broader bills are not caught. That keeps false
positives out; broaden KEYWORDS if you want more recall.

Stdlib only.
"""

import json
import os
import urllib.parse
import urllib.request
from datetime import datetime, timedelta, timezone

API = "https://api.congress.gov/v3/bill"
KEYWORDS = ["iran", "iranian", "tehran", "irgc", "revolutionary guard"]
MAX_ITEMS = 8
PAGE_LIMIT = 250   # api max per page
MAX_PAGES = 2

# API bill "type" -> (public-URL slug, display label)
_TYPE = {
    "HR": ("house-bill", "H.R."),
    "S": ("senate-bill", "S."),
    "HJRES": ("house-joint-resolution", "H.J.Res."),
    "SJRES": ("senate-joint-resolution", "S.J.Res."),
    "HCONRES": ("house-concurrent-resolution", "H.Con.Res."),
    "SCONRES": ("senate-concurrent-resolution", "S.Con.Res."),
    "HRES": ("house-resolution", "H.Res."),
    "SRES": ("senate-resolution", "S.Res."),
}


def _is_iran(title):
    t = (title or "").lower()
    return any(k in t for k in KEYWORDS)


def _bill_url(congress, btype, number):
    slug = _TYPE.get((btype or "").upper(), ("bill", ""))[0]
    return f"https://www.congress.gov/bill/{congress}th-congress/{slug}/{number}"


def _fmt_date(iso):
    try:
        d = datetime.strptime(iso, "%Y-%m-%d")
        return f"{d.month}/{d.day}"
    except (ValueError, TypeError):
        return iso or ""


def _parse_bills(bills):
    """Pure: API bill objects -> normalized Iran-related rows, newest action first."""
    out, seen = [], set()
    for b in bills or []:
        title = b.get("title")
        if not _is_iran(title):
            continue
        btype = (b.get("type") or "").upper()
        number = b.get("number")
        congress = b.get("congress")
        key = (congress, btype, number)
        if key in seen or not (btype and number and congress):
            continue
        seen.add(key)
        la = b.get("latestAction") or {}
        disp = _TYPE.get(btype, ("", btype))[1] or btype
        out.append({
            "id": f"{disp} {number}",
            "title": title.strip().rstrip("."),
            "action_date": la.get("actionDate", ""),
            "action_text": (la.get("text") or "").strip(),
            "url": _bill_url(congress, btype, number),
        })
    out.sort(key=lambda r: r["action_date"], reverse=True)
    return out


def fetch_iran_bills(days=14, api_key=None, now=None):
    """Recent Iran-related bills (best-effort; [] on missing key or any error)."""
    api_key = api_key or os.environ.get("CONGRESS_API_KEY")
    if not api_key:
        print("  [congress] no CONGRESS_API_KEY; skipping")
        return []
    now = now or datetime.now(timezone.utc)
    frm = (now - timedelta(days=days)).strftime("%Y-%m-%dT00:00:00Z")
    rows = []
    try:
        for page in range(MAX_PAGES):
            params = urllib.parse.urlencode({
                "format": "json", "limit": PAGE_LIMIT, "offset": page * PAGE_LIMIT,
                "fromDateTime": frm, "sort": "updateDate+desc", "api_key": api_key,
            }, safe="+")
            req = urllib.request.Request(f"{API}?{params}",
                                         headers={"Accept": "application/json"})
            data = json.loads(urllib.request.urlopen(req, timeout=30).read())
            bills = data.get("bills", [])
            rows += _parse_bills(bills)
            if len(bills) < PAGE_LIMIT:
                break
    except Exception as e:
        print(f"  [congress] ERR: {e!r}")
        return []
    # de-dup across pages, keep newest-action order, cap
    uniq, seen = [], set()
    for r in sorted(rows, key=lambda r: r["action_date"], reverse=True):
        if r["id"] in seen:
            continue
        seen.add(r["id"])
        uniq.append(r)
    return uniq[:MAX_ITEMS]


def render_section(days=14, api_key=None, now=None):
    """Markdown for the "U.S. Congress" section, or "" when nothing qualifies."""
    bills = fetch_iran_bills(days=days, api_key=api_key, now=now)
    if not bills:
        return ""
    lines = ["**U.S. Congress**"]
    for b in bills:
        tail = f" (latest action {_fmt_date(b['action_date'])}: {b['action_text']})" \
            if b["action_text"] else ""
        lines.append(f"- [{b['id']}]({b['url']}) — {b['title']}.{tail}")
    return "\n".join(lines)


if __name__ == "__main__":
    fixture = [
        {"congress": 119, "type": "S", "number": "1234",
         "title": "Iran Sanctions Accountability Act of 2026.",
         "latestAction": {"actionDate": "2026-08-05", "text": "Passed Senate with an amendment by Yea-Nay Vote."}},
        {"congress": 119, "type": "HR", "number": "77",
         "title": "A bill to counter Tehran's ballistic missile program",
         "latestAction": {"actionDate": "2026-08-08", "text": "Referred to the Committee on Foreign Affairs."}},
        {"congress": 119, "type": "HR", "number": "900",
         "title": "National Flood Insurance reauthorization",  # not Iran -> dropped
         "latestAction": {"actionDate": "2026-08-09", "text": "Introduced."}},
    ]
    rows = _parse_bills(fixture)
    assert len(rows) == 2, rows
    assert rows[0]["id"] == "H.R. 77", rows        # 8/8 newer than 8/5
    assert rows[0]["url"] == "https://www.congress.gov/bill/119th-congress/house-bill/77"
    assert rows[1]["id"] == "S. 1234"

    md = ["**U.S. Congress**"]
    for b in rows:
        md.append(f"- [{b['id']}]({b['url']}) — {b['title']}. (latest action "
                  f"{_fmt_date(b['action_date'])}: {b['action_text']})")
    print("\n".join(md))
    # No key -> empty, no raise.
    assert fetch_iran_bills(api_key=None) == []
    print("\ncongress.py self-test passed")
