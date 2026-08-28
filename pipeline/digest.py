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

# Section structure, per the CSIS input spec. ESSENTIAL headers are ALWAYS shown (with a
# "Nothing to Report." placeholder when empty). CONDITIONAL country headers appear only when
# they carry Iran-war-relevant news, in this fixed order. General is the always-shown
# catch-all (maritime/shipping data and cross-cutting items with no single country home).
ESSENTIAL = ["US", "Iran", "Lebanon", "Israel"]
CONDITIONAL = [
    "Bahrain", "Egypt", "Iraq", "Jordan", "Kuwait", "Oman", "Pakistan",
    "Qatar", "Saudi Arabia", "Syria", "Turkey", "UAE", "Yemen",
]
CATEGORIES = ESSENTIAL + CONDITIONAL + ["General"]      # canonical output order
ALWAYS_SHOWN = set(ESSENTIAL) | {"General"}
NO_NEWS = "- Nothing to Report."

# Aliases mapping the model's header spellings/variants to a canonical header. Anything
# unrecognized falls to General (see ensure_sections), so no real item is ever dropped.
_ALIASES = {
    "unitedstates": "US", "usa": "US", "unitedstatesofamerica": "US",
    "unitedarabemirates": "UAE",
    "ksa": "Saudi Arabia", "saudi": "Saudi Arabia", "kingdomofsaudiarabia": "Saudi Arabia",
    "turkiye": "Turkey",
    "houthi": "Yemen", "houthis": "Yemen",   # Saudi-Houthi front reports under Yemen
}

SYSTEM_PROMPT = """\
You format daily news items into the CSIS Middle East Program's "Iran War Update" house
style. You receive a JSON list of candidate news items (title, source, url) published on the
brief's own date (on a Monday the window covers the weekend, Saturday through Monday). Many
are duplicate reports of the same event from different outlets.

Produce the day's brief. Steps:
1. CLUSTER items that describe the same event. Report each real event ONCE. Different outlets
   word the same story differently and it may reach you from several sources (a wire, a
   newsletter, the Al Jazeera liveblog); fold them into a single bullet on the strongest
   source rather than repeating the event. Do not place the same development under two country
   headers — pick the one where it best belongs.
2. SELECT the genuinely significant developments. Drop opinion pieces, explainers, and
   trivia. Be COMPREHENSIVE: aim for roughly 15-40 real items across the whole brief, and
   cover every region that has real developments. Never omit an active region (Lebanon,
   Yemen, etc.) just because most of the day's volume is about one story (e.g. Hormuz).
   RELEVANCE: every item must bear on the Iran war specifically — Iran, its proxies and
   fronts (Hezbollah/Lebanon, the Houthis/Yemen/Red Sea, Iraqi militias), the Strait of
   Hormuz and Gulf shipping, U.S./allied action against Iran, and diplomacy to end the war.
   DROP general Middle East news with no Iran-war nexus (for example a West Bank settler
   incident, a UNRWA facility dispute, or a domestic Israeli or Syrian story) even when a
   major outlet reported it. Do NOT pad a section to look fuller: a header with no genuine
   Iran-war development gets "Nothing to Report." (essential/General) or is omitted
   (conditional country) — that is correct and expected, not a gap.
   SOURCE QUALITY: prefer the tiered outlets in step 7 and the Al Jazeera liveblog. Treat a
   claim carried only by an unfamiliar, low-authority, or non-news site (a blog, an SEO/
   aggregator domain, a company marketing page) with suspicion: drop it unless a tiered
   outlet corroborates it, rather than build a bullet on it alone.
   RECENCY: this is a DAILY update — include only developments that are NEW since the last
   brief. Date each item ("On [Weekday]") by when the EVENT happened, not when an outlet
   published a recap. Then DROP any development whose event is two or more days before today
   (the date is given below): a "Monday" item in a Wednesday brief is old news that was
   already covered, even if a fresh article re-reports it today — omit it unless today brought
   a genuinely new element (a new figure, a new named target, a new official response), in
   which case report only that new element. Keep events from today and the day before. The
   one exception: a Monday brief covers the whole weekend, so Saturday and Sunday events are
   new there. When in doubt about whether an older event is genuinely new today, leave it out.
3. CATEGORIZE under these headers. ALWAYS include these four, in this order, even with no
   news: US, Iran, Lebanon, Israel. Then include any of these country headers ONLY IF they
   have Iran-war-relevant news, in this exact order: Bahrain, Egypt, Iraq, Jordan, Kuwait,
   Oman, Pakistan, Qatar, Saudi Arabia, Syria, Turkey, UAE, Yemen. End with General for
   maritime/shipping data and cross-cutting items that have no single country home. For an
   essential header (or General) with no development today, write the header followed by a
   single bullet exactly: "- Nothing to Report." OMIT a conditional country header entirely
   when it has no news — do not write a placeholder for it.
   THRESHOLD for a conditional country header: give a conditional country its own header only
   when it has a substantial block — roughly three or more item bullets, or a single major
   development. If a conditional country has only one or two minor items, do NOT open a header
   for it; fold those items into General instead (each still a normal bullet, naming the
   country in the text). This keeps the brief from sprouting thin one- or two-line country
   sections. The four essential headers (US, Iran, Lebanon, Israel) are exempt — they always
   appear regardless of how many bullets they carry.
4. WRITE each item as one bullet: "On [Weekday], [actor] [verb] [what happened]."
   - Put the source hyperlink on the reporting verb, Markdown style: [said](url).
   - Neutral verbs only: said, reported, wrote, announced, told, confirmed, warned. Never
     use "claim" to imply doubt.
   - DEPTH — this is what makes the brief valuable, so err toward MORE detail, not less.
     Each item may include a "summary" carrying the article's or post's actual text. For every
     significant development, add an indented sub-bullet for EACH distinct piece of substance
     in that text: each direct quote, each specific figure (counts, tolls, barrels, vessels,
     percentages, dates), each named condition or demand, and each material follow-on fact.
     A major development — a policy announcement, a senior official's remarks or press
     conference, a strike, a shipping-data release — often warrants FOUR TO EIGHT sub-bullets.
     Reproduce direct quotes VERBATIM and in full, in quotation marks; never paraphrase a
     quote into your own words or shorten it. Use ONLY what is present in that item's title or
     summary — never add a quote, number, or fact from your own knowledge. Only a genuinely
     thin item (a bare headline with no further text in its summary) gets a single bullet.
     Example of the target density for one item:
       - On Monday, Treasury Secretary Bessent [held](url) a media conference to unveil "D-Day."
         - "Let there be no ambiguity as to the position of the United States," Bessent said.
         - He said the U.S. is expanding secondary sanctions to digital assets, technology,
           gold, aviation, and shipping.
         - The Treasury has sanctioned nearly 60 entities, individuals, and vessels, he said.
         - "I'm not going to set a timeline, but we do not have infinite patience here."
5. PRIORITIES — cover these threads thoroughly whenever the input supports them:
   - Strikes: name who launched it and what was targeted, the timing, the stated motivation,
     and the number of injured or killed.
   - Shipping: transit and traffic data (Kpler, MarineTraffic, UKMTO) with the specific
     numbers, and any disruption to the Strait of Hormuz or the Bab el-Mandeb Strait.
   - The Lebanon-Israel front: Israeli strikes on south Lebanon and statements by senior
     officials on that front.
   - The Saudi-Houthi / Yemen front: strikes, statements from Houthi, Saudi, and Yemeni
     government officials, and disruptions to Red Sea / Bab el-Mandeb shipping.
   - Statements by high-ranking officials on the conflict.
   - High-level meetings and phone calls: report confirmed meetings, but do NOT include the
     contents of a conversation unless the details are significant.
6. SOURCING: if a cluster has two or more independent outlets, it is corroborated; pick the
   strongest source for the link. If an item rests on a single source and is load-bearing
   (a death toll, a strike, an official position), append ` [single-source]`.
7. PRESTIGE (source tiers): prefer the strongest available outlet for each link. Tier one —
   Reuters, Al Jazeera, Axios, The Wall Street Journal, The New York Times. Tier two — The
   National, L'Orient Today, The Times of Israel, Haaretz, and U.S. Treasury or State
   Department statements. Tier three — The Washington Post, Asharq Al-Awsat, Syria's SANA,
   Al-Monitor. Do not drop a genuinely significant development a tier-one or tier-two outlet
   reported.
8. Only use URLs present in the input. Never invent a link, a quote, a number, or an event
   not present in an item's title or summary.

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
    """Enforce the section structure: the four ESSENTIAL headers (and General) are always
    present, in canonical order, filling any empty one with the "Nothing to Report."
    placeholder; a CONDITIONAL country header is emitted only when it has news.

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
        if not content and c not in ALWAYS_SHOWN:
            continue   # conditional country with no news is omitted entirely
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
    # Budget generously: if a model rejects disabled thinking and we fall back to thinking ON,
    # the reasoning shares this budget with the brief, and 8000 left a bullet truncated
    # mid-word ("...shipping Sa"). 16000 leaves ample room for the full brief either way.
    create_kwargs = dict(
        model=model,
        max_tokens=16000,
        system=SYSTEM_PROMPT,
        messages=[{
            "role": "user",
            "content": (f"Today is {date_label}. Use only the M/D part in the header line. "
                        f"Apply the RECENCY rule against today's weekday: drop developments "
                        f"whose event is two or more days before today. Here are {len(slim)} "
                        f"candidate items as JSON:\n\n{json.dumps(slim, ensure_ascii=False)}"),
        }],
    )
    try:
        msg = client.messages.create(thinking={"type": "disabled"}, **create_kwargs)
    except anthropic.BadRequestError:
        msg = client.messages.create(**create_kwargs)
    # The model may emit a thinking block before the answer, so content[0] is not
    # necessarily the text. Concatenate every text block and ignore the rest.
    text = "".join(
        getattr(block, "text", "") for block in msg.content
        if getattr(block, "type", None) == "text"
    ).strip()
    # Belt and suspenders: if the response was cut at the token limit, never ship a
    # half-finished bullet — drop any incomplete trailing line.
    if getattr(msg, "stop_reason", None) == "max_tokens":
        print("  [digest] warning: response hit max_tokens; trimming incomplete tail")
    return _strip_incomplete_tail(text)


_SENTENCE_END = (".", "!", "?", ")", "]", '"', "'", "”", "’", ":")


def _strip_incomplete_tail(md):
    """Drop a trailing bullet that doesn't end in sentence punctuation (a truncated line).
    House-style bullets always end with '.', so a complete brief is unaffected."""
    lines = md.rstrip().split("\n")
    while lines:
        last = lines[-1].rstrip()
        if not last:
            lines.pop()
            continue
        if last.lstrip().startswith(("-", "*")) and not last.endswith(_SENTENCE_END):
            lines.pop()
            continue
        break
    return "\n".join(lines).strip()


def build_brief():
    import anthropic

    items_path = latest_items_file()
    items = json.loads(items_path.read_text(encoding="utf-8"))

    # Interleave across topics, then trim: keep the fields the model needs, cap the count.
    pool = _interleave(items)
    slim = [{"title": it["title"], "source": it["source"], "url": it["url"],
             "published": it.get("published") or "",
             "summary": (it.get("summary") or "")[:1800]}
            for it in pool[:MAX_CANDIDATES]]

    today = datetime.now(timezone.utc)
    # Include the weekday so the model can apply the RECENCY rule (drop events 2+ days old);
    # the user message tells it to use only the M/D part for the header line.
    date_label = f"{today.strftime('%A')}, {today.month}/{today.day}"

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

    # Enforce the house rule against "claim" mechanically (the prompt asks for it, but the
    # model still slips; this rewrites the reporting-verb uses to a neutral verb).
    brief_md = validate.neutralize_claim(brief_md)

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
