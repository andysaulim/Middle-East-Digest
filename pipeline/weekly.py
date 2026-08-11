"""
weekly.py — Iran War Update, Friday "Week in Review"

The daily brief answers "what happened today." The archive (data/archive.db, built up by
collect.py) can answer what a single email thread never could: how the week trended. This
module reads the last seven days of collected items, computes a few factual tallies
(strikes, tanker/maritime incidents, casualties, Hormuz mentions, ...), asks Claude to
synthesize the arc of the week in house style, and appends a deterministic "By the numbers"
block so the counts are exact rather than model-estimated.

Delivered the same way as the daily brief (render.py -> deliver.py), with its own subject.
Runs Fridays via .github/workflows/iran-weekly.yml.

Requires: pip install anthropic ; env var ANTHROPIC_API_KEY. Reuses the committed archive,
so it needs no source fetching and no new secrets.
"""

import os
import sqlite3
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import collect  # DB_PATH
import render
import deliver

OUT_DIR = Path(__file__).parent / "out"
OUT_DIR.mkdir(exist_ok=True)

MODEL = os.environ.get("IRAN_BRIEF_PRIMARY_MODEL", "claude-opus-4-8")
WINDOW_DAYS = 7
MAX_TITLES = 400   # cap headlines handed to the model

# Factual tallies computed from the archive (label -> SQL LIKE patterns, OR-matched on title).
TREND_GROUPS = {
    "Strikes / air raids": ["%strike%", "%struck%", "%air raid%", "%airstrike%"],
    "Tanker / maritime incidents": ["%tanker%", "%vessel%", "%shipping%"],
    "Casualties reported": ["%killed%", "%dead%", "%casualt%", "%wounded%"],
    "Strait of Hormuz": ["%hormuz%"],
    "Houthi / Red Sea": ["%houthi%", "%red sea%", "%bab el mandeb%"],
    "Nuclear program": ["%nuclear%", "%enrich%", "%uranium%"],
    "Hezbollah / Lebanon": ["%hezbollah%", "%lebanon%"],
}

SYSTEM_PROMPT = """\
You write the CSIS Middle East Program's weekly "Iran War Update — Week in Review." You
receive the week's collected headlines (title, source, url, date) and a set of factual
tallies. Synthesize the arc of the week, not a day-by-day list:

1. Open with a 2-4 sentence overview of the week's dominant threads.
2. Then the most consequential developments as bullets, grouped under the standard regional
   headers where useful (US, Iran, Lebanon, Israel, Saudi Arabia/Yemen/Iraq, General).
   Emphasize what changed over the week and any escalation or de-escalation.
3. You may link a specific development using ONLY a url present in the input; never invent a
   link, a number, or an event not supported by the headlines. Generalize, do not fabricate.

House style: neutral verbs (said, reported, announced, warned); never "claim" to imply
doubt. U.S. and U.K. keep periods. Spell out percentages. Serial comma. No em-dashes.
Numerals for specific figures.

Output ONLY the review in Markdown, starting with the header line the user gives you. No
preamble and no commentary after.
"""


def _cutoff_str(today):
    return (today - timedelta(days=WINDOW_DAYS)).strftime("%Y-%m-%d")


def week_items(con, cutoff_str):
    """(collected_date, source, title, url) for items collected on/after the cutoff."""
    rows = con.execute(
        "SELECT collected_date, source, title, url FROM items "
        "WHERE collected_date >= ? ORDER BY collected_date",
        (cutoff_str,),
    ).fetchall()
    return [{"date": d, "source": s, "title": t, "url": u} for d, s, t, u in rows]


def trend_counts(con, cutoff_str):
    """label -> count of items in the window whose title matches any of the group's patterns."""
    counts = {}
    for label, patterns in TREND_GROUPS.items():
        where = " OR ".join("title LIKE ?" for _ in patterns)
        n = con.execute(
            f"SELECT COUNT(*) FROM items WHERE collected_date >= ? AND ({where})",
            (cutoff_str, *patterns),
        ).fetchone()[0]
        counts[label] = n
    return counts


def _by_the_numbers(counts):
    """Deterministic tally block (exact counts, not model-estimated)."""
    lines = ["**By the numbers this week**"]
    for label, n in counts.items():
        lines.append(f"- {label}: {n} item{'s' if n != 1 else ''} in the archive.")
    return "\n".join(lines)


def _synthesize(client, model, items, counts, span_label, header):
    import anthropic
    import json
    slim = [{"title": it["title"], "source": it["source"], "url": it["url"],
             "date": it["date"]} for it in items[:MAX_TITLES]]
    payload = {"header": header, "tallies": counts, "headlines": slim}
    create_kwargs = dict(
        model=model,
        max_tokens=8000,
        system=SYSTEM_PROMPT,
        messages=[{"role": "user", "content": (
            f"The week is {span_label}. Start the review with exactly this header line:\n"
            f"{header}\n\nHere is the week's data as JSON:\n\n"
            f"{json.dumps(payload, ensure_ascii=False)}")}],
    )
    try:
        msg = client.messages.create(thinking={"type": "disabled"}, **create_kwargs)
    except anthropic.BadRequestError:
        msg = client.messages.create(**create_kwargs)
    return "".join(getattr(b, "text", "") for b in msg.content
                   if getattr(b, "type", None) == "text").strip()


def build_weekly():
    import anthropic

    today = datetime.now(timezone.utc).date()
    cutoff = _cutoff_str(today)
    span_label = (f"{(today - timedelta(days=WINDOW_DAYS)).month}/"
                  f"{(today - timedelta(days=WINDOW_DAYS)).day}-{today.month}/{today.day}")
    header = f"**Iran War Update — Week in Review ({span_label}):**"

    con = sqlite3.connect(collect.DB_PATH)
    items = week_items(con, cutoff)
    counts = trend_counts(con, cutoff)
    con.close()

    if not items:
        print("No archived items in the last 7 days; skipping weekly rollup.")
        return None

    client = anthropic.Anthropic()
    review_md = _synthesize(client, MODEL, items, counts, span_label, header)
    review_md = f"{review_md}\n\n{_by_the_numbers(counts)}"

    out_path = OUT_DIR / f"weekly_{today.strftime('%Y-%m-%d')}.md"
    out_path.write_text(review_md, encoding="utf-8")
    print(f"Wrote {out_path} ({len(review_md)} chars, {len(items)} items across the week)")

    html_path = render.render(out_path)
    deliver.deliver(html_path, subject=f"[DRAFT] Iran War Update — Week in Review ({span_label})")
    return out_path


# --- self-test (SQL helpers only, on a temp DB; no API) -------------------
def _selftest():
    con = sqlite3.connect(":memory:")
    con.execute("""CREATE TABLE items (url TEXT PRIMARY KEY, collected_date TEXT,
                   source TEXT, collector TEXT, title TEXT, summary TEXT, published TEXT)""")
    rows = [
        ("u1", "2026-08-10", "Reuters", "g", "Israel strike kills fighters in Lebanon", "", ""),
        ("u2", "2026-08-09", "AP", "g", "Tanker attacked near Strait of Hormuz", "", ""),
        ("u3", "2026-08-08", "AJ", "g", "Houthi drone downed over Red Sea", "", ""),
        ("u4", "2026-07-01", "X", "g", "Old strike from last month", "", ""),  # outside window
    ]
    con.executemany("INSERT INTO items VALUES (?,?,?,?,?,?,?)", rows)
    cutoff = _cutoff_str(datetime(2026, 8, 10, tzinfo=timezone.utc).date())
    items = week_items(con, cutoff)
    assert len(items) == 3, items                       # July row excluded by window
    counts = trend_counts(con, cutoff)
    assert counts["Strikes / air raids"] == 1, counts   # only the in-window Lebanon strike
    assert counts["Tanker / maritime incidents"] == 1, counts
    assert counts["Strait of Hormuz"] == 1, counts
    assert counts["Houthi / Red Sea"] == 1, counts
    block = _by_the_numbers(counts)
    assert "By the numbers this week" in block
    con.close()
    print("weekly.py self-test passed")


if __name__ == "__main__":
    if "--selftest" in sys.argv:
        _selftest()
    else:
        build_weekly()
