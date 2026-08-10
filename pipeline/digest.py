"""
digest.py — Iran War Update, cluster + format (Phases 2-3)

Reads the day's collected candidates (from collect.py), sends them to Claude with the
house-style formatter instructions, and gets back the finished brief. Claude does the
clustering, significance selection, categorization, hyphenation of source links, and the
two-source / single-source tagging in one structured pass.

The output is then run through validate.py before it ships. If a CRITICAL check
fails (a stub-length brief, a fabricated link, a missing header), the brief is
regenerated — escalating from the fast model to a stronger one, mirroring the
Korea/Japan digests' validate-and-regenerate guardrail.

After validation, every standard country header is guaranteed present (a country with no
news shows "Nothing to Report." rather than vanishing), and a curated "Dates ahead"
section is appended from calendar_data.py.

System prompt below is the machine version of `Iran War Update — Formatter Prompt.md`;
keep the two in sync.

Requires: pip install anthropic ; env var ANTHROPIC_API_KEY.
Models: IRAN_BRIEF_MODEL is the first-attempt (fast) model (default claude-sonnet-5);
IRAN_BRIEF_PRIMARY_MODEL is the escalation model used on a validation retry
(default claude-opus-4-8).
"""

import os
import json
import re
import sys
from collections import OrderedDict
from itertools import zip_longest
from datetime import datetime, timezone
from pathlib import Path

import validate
import calendar_data
import congress
import history_data

DATA_DIR = Path(__file__).parent / "data"
OUT_DIR = Path(__file__).parent / "out"
OUT_DIR.mkdir(exist_ok=True)

# Fast first attempt, stronger model on a validation-failure retry (Korea/Japan pattern).
FAST_MODEL = os.environ.get("IRAN_BRIEF_MODEL", "claude-sonnet-5")
PRIMARY_MODEL = os.environ.get("IRAN_BRIEF_PRIMARY_MODEL", "claude-opus-4-8")
MAX_ATTEMPTS = 3       # 1 fast attempt + up to 2 escalated retries
MAX_CANDIDATES = 300   # cap items sent to the model (interleaved across topics first)

# Section headers, in the order the human tracker uses them. The Gulf/Iraq theater is one
# combined header; countries that appear only occasionally (Oman, Egypt, Jordan, Syria, the
# Caspian) are not standing headers — their items flow into the combined header or General
# via _ALIASES below, matching the real product.
CATEGORIES = [
    "US", "Iran", "Lebanon", "Israel", "Saudi Arabia/Yemen/Iraq", "General",
]
NO_NEWS = "- Nothing to Report."

_GULF = "Saudi Arabia/Yemen/Iraq"
# Aliases the model might emit, mapped to the canonical header. Anything unrecognized falls
# to General (see ensure_sections), so no real item is ever dropped.
_ALIASES = {
    "unitedstates": "US", "usa": "US",
    # the combined Gulf/Iraq theater, however the model splits or spells it
    "saudiarabiayemeniraq": _GULF, "yemensaudiarabiairaq": _GULF,
    "yemensaudiarabia": _GULF, "saudiarabiayemen": _GULF,
    "yemen": _GULF, "saudiarabia": _GULF, "saudi": _GULF, "iraq": _GULF,
    "gulf": _GULF, "redsea": _GULF,
    # occasional countries fold into General
    "oman": "General", "egypt": "General", "jordan": "General",
    "syria": "General", "caspian": "General", "caspiansea": "General",
}

SYSTEM_PROMPT = """\
You format daily news items into the CSIS Middle East Program's "Iran War Update" house
style. You receive a JSON list of candidate news items (title, source, url) collected in
the last 24 hours (three days on a Monday, covering the weekend). Many are duplicate
reports of the same event from different outlets.

Produce the day's brief. Steps:
1. CLUSTER items that describe the same event.
2. SELECT the genuinely significant developments. Drop opinion pieces, explainers, and
   trivia. Be COMPREHENSIVE: aim for roughly 15-40 real items across the whole brief, and
   cover every region that has real developments. Never omit an active region (Lebanon,
   Yemen, etc.) just because most of the day's volume is about one story (e.g. Hormuz).
3. CATEGORIZE into exactly these six headers, ALWAYS including EVERY header in this exact
   order, even when a header has no news:
   US, Iran, Lebanon, Israel, Saudi Arabia/Yemen/Iraq, General.
   "Saudi Arabia/Yemen/Iraq" is one combined header covering the whole Gulf/Iraq theater
   (Houthi and Red Sea attacks, Saudi Arabia, Yemen, Iraqi militias). Developments in Oman,
   Egypt, Jordan, Syria, or elsewhere in the region that do not fit a country header go under
   General. For a header with no genuine development today, write the header followed by a
   single bullet exactly: "- Nothing to Report." Do not drop any header.
4. WRITE each item as one bullet: "On [Weekday], [actor] [verb] [what happened]."
   - Put the source hyperlink on the reporting verb, Markdown style: [said](url).
   - Neutral verbs only: said, reported, wrote, announced, told, confirmed, warned. Never
     use "claim" to imply doubt.
   - Add an indented sub-bullet for a direct quote, a casualty or transit figure, or a
     load-bearing follow-on detail. Keep specific numbers (counts, tolls, percentages).
5. SOURCING: if a cluster has two or more independent outlets, it is corroborated; pick the
   strongest source for the link. If an item rests on a single source and is load-bearing
   (a death toll, a strike, an official position), append ` [single-source]`.
6. PRESTIGE: when a development was reported by a strong outlet — The Wall Street Journal,
   The New York Times, Financial Times, Reuters, The Associated Press, Bloomberg, The
   Economist, The Washington Post, Al Jazeera, or a recognized regional specialist — prefer
   it as the linked source, and do not drop a genuinely significant development they
   reported.
7. Only use URLs present in the input. Never invent a link or an event not in the input.

Mechanics: U.S. and U.K. keep periods. Spell out percentages ("42 percent"). Serial comma.
No em-dashes. Numerals for specific figures.

Output ONLY the finished brief in Markdown, starting with the line:
**Some updates on the Iran war (M/D):**
Use the date the user gives you. No preamble, no commentary after.
"""


def latest_items_file():
    files = sorted(DATA_DIR.glob("items_*.json"))
    if not files:
        sys.exit("No items_*.json found. Run collect.py first.")
    return files[-1]


def _interleave(items):
    """Round-robin across collectors (queries/feeds) so every topic is represented
    before the candidate cap, instead of front-loading whichever query returned first.
    Without this, the first two Google News queries alone fill the cap and later
    regions (Lebanon, Yemen, ...) never reach the model."""
    groups = OrderedDict()
    for it in items:
        groups.setdefault(it.get("collector") or "?", []).append(it)
    ordered = []
    for row in zip_longest(*groups.values()):
        ordered.extend(it for it in row if it is not None)
    return ordered


def _header_name(line):
    """If a line is a bold section header (**X**, no link), return X; else None."""
    s = line.strip()
    if s.startswith("**") and s.endswith("**") and "](" not in s and len(s) > 4:
        return s.strip("*").strip()
    return None


def ensure_sections(brief_md):
    """Guarantee every standard header is present, in canonical order, filling any header
    that has no items with the "Nothing to Report." placeholder.

    Reorders the model's sections into CATEGORIES order. Content under an unrecognized
    header flows into General rather than being dropped, so no real item is lost."""
    lines = brief_md.splitlines()
    if not lines:
        return brief_md
    title, body = lines[0], lines[1:]

    canon_by_key = {re.sub(r"[^a-z]", "", c.lower()): c for c in CATEGORIES}
    sections, current = OrderedDict(), None
    for line in body:
        h = _header_name(line)
        if h is not None:
            key = re.sub(r"[^a-z]", "", h.lower())
            current = canon_by_key.get(key) or _ALIASES.get(key) or "General"
            sections.setdefault(current, [])
            continue
        if current is None:
            continue  # stray preamble before the first header
        # skip the model's own placeholders; we re-add them uniformly below
        if line.strip().lower().startswith("- no developments reported"):
            continue
        sections.setdefault(current, []).append(line)

    out = [title]
    for c in CATEGORIES:
        content = [ln for ln in sections.get(c, []) if ln.strip()]
        out.append("")
        out.append(f"**{c}**")
        out.extend(content if content else [NO_NEWS])
    return "\n".join(out).strip()


def _generate(client, model, slim, date_label):
    """One drafting pass with a given model. Returns the brief Markdown."""
    import anthropic
    # Disable extended thinking: on current models (e.g. claude-sonnet-5) adaptive
    # thinking is ON by default, and it consumes the max_tokens budget — which left
    # the brief truncated to a near-empty stub on the first live run. This is a
    # deterministic clustering/formatting task, so no thinking is needed; give the
    # whole budget to the brief. (If a model rejects disabled thinking, e.g. Fable 5,
    # retry without the parameter and rely on a large max_tokens.)
    create_kwargs = dict(
        model=model,
        max_tokens=8000,
        system=SYSTEM_PROMPT,
        messages=[{
            "role": "user",
            "content": (f"Today is {date_label}. Here are {len(slim)} candidate items "
                        f"as JSON:\n\n{json.dumps(slim, ensure_ascii=False)}"),
        }],
    )
    try:
        msg = client.messages.create(thinking={"type": "disabled"}, **create_kwargs)
    except anthropic.BadRequestError:
        msg = client.messages.create(**create_kwargs)
    # The model may emit a thinking block before the answer, so content[0] is not
    # necessarily the text. Concatenate every text block and ignore the rest.
    return "".join(
        getattr(block, "text", "") for block in msg.content
        if getattr(block, "type", None) == "text"
    ).strip()


def build_brief():
    import anthropic

    items_path = latest_items_file()
    items = json.loads(items_path.read_text(encoding="utf-8"))

    # Interleave across topics, then trim: keep the fields the model needs, cap the count.
    pool = _interleave(items)
    slim = [{"title": it["title"], "source": it["source"], "url": it["url"]}
            for it in pool[:MAX_CANDIDATES]]

    today = datetime.now(timezone.utc)
    date_label = f"{today.month}/{today.day}"

    client = anthropic.Anthropic()  # reads ANTHROPIC_API_KEY

    # Validate-and-regenerate: draft, check against the input, and on a CRITICAL
    # failure retry with a stronger model (fast first, then escalate).
    attempts = [FAST_MODEL] + [PRIMARY_MODEL] * (MAX_ATTEMPTS - 1)
    brief_md, used_model, last_critical = "", FAST_MODEL, []
    for i, model in enumerate(attempts, start=1):
        brief_md, used_model = _generate(client, model, slim, date_label), model
        critical, warnings = validate.validate_brief(brief_md, slim)
        for w in warnings:
            print(f"  [validate] warning: {w}")
        if not critical:
            if i > 1:
                print(f"  [validate] passed on attempt {i} (model={model})")
            break
        last_critical = critical
        print(f"  [validate] attempt {i} (model={model}) FAILED: {critical}")
        if i < len(attempts):
            print(f"  [validate] regenerating with {attempts[i]} ...")
    else:
        # Retries exhausted. Rather than hard-fail the whole run, repair the last
        # attempt by dropping only the bullets with unverifiable links (upholds
        # SOURCE-OR-SKIP), then ship if the remainder is still a usable brief.
        repaired = validate.repair_brief(brief_md, slim)
        rc, rw = validate.validate_brief(repaired, slim)
        blocking = [c for c in rc if "not in the collected input" not in c]
        if repaired and not blocking:
            for w in rw:
                print(f"  [validate] warning (post-repair): {w}")
            print(f"  [validate] repaired after {len(attempts)} attempts "
                  f"(dropped items with unverifiable links)")
            brief_md = repaired
        else:
            raise RuntimeError(
                f"Brief failed validation after {len(attempts)} attempts and repair: "
                f"{last_critical}"
            )

    # Guarantee every country header is present (no-news countries show a placeholder),
    # then append the deterministic tail sections (rendered from source, never the model,
    # so the brief can't invent a bill, a date, or a historical event): U.S. Congress, then
    # "This day in history," then the curated "Dates ahead."
    brief_md = ensure_sections(brief_md)
    for extra in (
        congress.render_section(),
        history_data.render_section(today.date()),
        calendar_data.render_section(today.date()),
    ):
        if extra:
            brief_md = f"{brief_md}\n\n{extra}"

    out_path = OUT_DIR / f"brief_{today.strftime('%Y-%m-%d')}.md"
    out_path.write_text(brief_md, encoding="utf-8")
    print(f"Wrote {out_path} ({len(brief_md)} chars, model={used_model})")
    return out_path


if __name__ == "__main__":
    build_brief()
