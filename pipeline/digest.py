"""
digest.py — Iran War Update, cluster + format (Phases 2-3)

Reads the day's collected candidates (from collect.py), sends them to Claude with the
house-style formatter instructions, and gets back the finished brief. Claude does the
clustering, significance selection, categorization, hyphenation of source links, and the
two-source / single-source tagging in one structured pass.

System prompt below is the machine version of `Iran War Update — Formatter Prompt.md`;
keep the two in sync.

Requires: pip install anthropic ; env var ANTHROPIC_API_KEY.
Model is configurable via IRAN_BRIEF_MODEL (default: claude-sonnet-5).
"""

import os
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

import anthropic

DATA_DIR = Path(__file__).parent / "data"
OUT_DIR = Path(__file__).parent / "out"
OUT_DIR.mkdir(exist_ok=True)

MODEL = os.environ.get("IRAN_BRIEF_MODEL", "claude-sonnet-5")
MAX_CANDIDATES = 150   # cap items sent to the model to control token cost

SYSTEM_PROMPT = """\
You format daily news items into the CSIS Middle East Program's "Iran War Update" house
style. You receive a JSON list of candidate news items (title, source, url) collected in
the last 24 hours. Many are duplicate reports of the same event from different outlets.

Produce the day's brief. Steps:
1. CLUSTER items that describe the same event.
2. SELECT the genuinely significant developments. Drop opinion pieces, explainers, and
   trivia. Aim for 12-25 items across the whole brief, not everything.
3. CATEGORIZE each into exactly these headers, in this order (omit an empty header):
   US, Iran, Lebanon, Israel, Yemen / Saudi Arabia, Oman, General.
4. WRITE each item as one bullet: "On [Weekday], [actor] [verb] [what happened]."
   - Put the source hyperlink on the reporting verb, Markdown style: [said](url).
   - Neutral verbs only: said, reported, wrote, announced, told, confirmed, warned. Never
     use "claim" to imply doubt.
   - Add an indented sub-bullet for a quote or a follow-on detail when warranted.
5. SOURCING: if a cluster has two or more independent outlets, it is corroborated; pick the
   strongest source for the link. If an item rests on a single source and is load-bearing
   (a death toll, a strike, an official position), append ` [single-source]`.
6. Only use URLs present in the input. Never invent a link or an event not in the input.

Mechanics: U.S. and U.K. keep periods. Spell out percentages ("42 percent"). Serial comma.
No em-dashes. Numerals for specific figures.

Output ONLY the finished brief in Markdown, starting with the line:
**Some updates on the Iran war (M/D):**
Use today's date the user gives you. No preamble, no commentary after.
"""


def latest_items_file():
    files = sorted(DATA_DIR.glob("items_*.json"))
    if not files:
        sys.exit("No items_*.json found. Run collect.py first.")
    return files[-1]


def build_brief():
    items_path = latest_items_file()
    items = json.loads(items_path.read_text(encoding="utf-8"))

    # Trim payload: keep the fields the model needs, cap the count.
    slim = [{"title": it["title"], "source": it["source"], "url": it["url"]}
            for it in items[:MAX_CANDIDATES]]

    today = datetime.now(timezone.utc)
    date_label = f"{today.month}/{today.day}"

    client = anthropic.Anthropic()  # reads ANTHROPIC_API_KEY
    msg = client.messages.create(
        model=MODEL,
        max_tokens=4000,
        system=SYSTEM_PROMPT,
        messages=[{
            "role": "user",
            "content": (f"Today is {date_label}. Here are {len(slim)} candidate items "
                        f"as JSON:\n\n{json.dumps(slim, ensure_ascii=False)}"),
        }],
    )
    # The model may emit a thinking block before the answer, so content[0] is not
    # necessarily the text. Concatenate every text block and ignore the rest.
    brief_md = "".join(
        getattr(block, "text", "") for block in msg.content
        if getattr(block, "type", None) == "text"
    ).strip()
    if not brief_md:
        raise RuntimeError(
            f"No text block in model response (blocks: "
            f"{[getattr(b, 'type', '?') for b in msg.content]})"
        )

    out_path = OUT_DIR / f"brief_{today.strftime('%Y-%m-%d')}.md"
    out_path.write_text(brief_md, encoding="utf-8")
    print(f"Wrote {out_path} ({len(brief_md)} chars, model={MODEL})")
    return out_path


if __name__ == "__main__":
    build_brief()
