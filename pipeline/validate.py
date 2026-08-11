"""
validate.py — Iran War Update, brief validation (failsafe stage)

Ported from the Korea/Japan digest guardrails. After the model drafts the brief,
this checks it against the collected input before anything ships. The digest step
regenerates (escalating to a stronger model) when a CRITICAL check fails.

CRITICAL (fail -> regenerate / escalate, then raise if still unresolved):
  - empty or stub-length brief (catches truncated / near-empty output)
  - a Markdown link whose URL was NOT in the collected input. This mechanically
    enforces SOURCE-OR-SKIP: the model may only link things it was given, never
    invent a URL.
  - missing the house-style header line

WARNING (logged, non-blocking):
  - top-level item count outside the 15-40 house target ("No developments reported."
    placeholder bullets do not count)
  - "claim" used as a reporting verb (house style avoids it to imply doubt)
  - no prestige-outlet items present in today's input (informational)

Stdlib only — no dependencies, so it runs in the dry path too.
"""

import re

# Thresholds
MIN_CHARS = 400            # below this the brief is almost certainly truncated
MIN_ITEMS_CRITICAL = 3     # fewer top-level bullets than this = incomplete
TARGET_MIN, TARGET_MAX = 15, 40   # house target; outside this is a (non-blocking) warning

# Strong outlets we want represented when they reported a development. Matched
# (case-insensitively) against each item's `source` name.
PRESTIGE = [
    "wall street journal", "wsj", "new york times", "nyt", "financial times",
    "ft.com", "reuters", "associated press", "ap news", "bloomberg",
    "the economist", "washington post", "the guardian", "bbc", "npr",
]

_LINK_RE = re.compile(r"\[[^\]]+\]\((https?://[^)]+)\)")
_TOP_BULLET_RE = re.compile(r"^[-*]\s+", re.MULTILINE)   # non-indented bullets only
_CLAIM_RE = re.compile(r"\bclaim(s|ed|ing)?\b", re.IGNORECASE)
_NO_NEWS_RE = re.compile(
    r"^[-*]\s+(No developments reported|Nothing to Report)\.?\s*$",
    re.IGNORECASE | re.MULTILINE)


def extract_urls(md):
    """Every Markdown-link URL in the text, in order."""
    return _LINK_RE.findall(md or "")


def prestige_count(items):
    """How many collected items came from a prestige outlet."""
    n = 0
    for it in items:
        source = (it.get("source") or "").lower()
        if any(p in source for p in PRESTIGE):
            n += 1
    return n


def repair_brief(brief_md, items):
    """Drop top-level bullets whose links are not in the input, keeping the rest.

    Used as a last resort after regeneration is exhausted: it upholds SOURCE-OR-SKIP
    (no fabricated links ship) without failing the whole brief over one bad bullet.
    A dropped bullet takes its indented sub-bullets with it.
    """
    allowed = {(it.get("url") or "").strip() for it in items}
    lines = (brief_md or "").splitlines()
    out, i = [], 0
    while i < len(lines):
        line = lines[i]
        if _TOP_BULLET_RE.match(line) and any(u not in allowed for u in extract_urls(line)):
            i += 1
            # skip this bullet's indented sub-bullets
            while i < len(lines) and lines[i][:1] in (" ", "\t"):
                i += 1
            continue
        out.append(line)
        i += 1
    return "\n".join(out).strip()


def validate_brief(brief_md, items):
    """Check a drafted brief against the collected input.

    Returns (critical, warnings): two lists of human-readable strings. An empty
    `critical` list means the brief is safe to ship.
    """
    critical, warnings = [], []
    text = (brief_md or "").strip()

    if not text:
        return ["brief is empty"], warnings

    # Stub / truncation
    if len(text) < MIN_CHARS:
        critical.append(f"brief is only {len(text)} chars (< {MIN_CHARS}); likely truncated")

    # House header
    first_line = text.splitlines()[0]
    if "updates on the iran war" not in first_line.lower():
        critical.append(f"missing house header line (first line: {first_line[:60]!r})")

    # SOURCE-OR-SKIP: every linked URL must have come from the input
    allowed = {(it.get("url") or "").strip() for it in items}
    unknown = [u for u in extract_urls(text) if u not in allowed]
    if unknown:
        critical.append(
            f"{len(unknown)} link(s) not in the collected input (possible fabrication): "
            f"{unknown[:3]}"
        )

    # Item count (excluding "No developments reported." placeholders, which are not news)
    n_items = len(_TOP_BULLET_RE.findall(text)) - len(_NO_NEWS_RE.findall(text))
    if n_items < MIN_ITEMS_CRITICAL:
        critical.append(f"only {n_items} top-level item(s); brief looks incomplete")
    elif n_items < TARGET_MIN or n_items > TARGET_MAX:
        warnings.append(f"{n_items} items (house target is {TARGET_MIN}-{TARGET_MAX})")

    # Style
    if _CLAIM_RE.search(text):
        warnings.append('uses "claim" (house style avoids it to imply doubt)')

    # Prestige (informational only — freeform Markdown with redirect URLs cannot be
    # checked reliably, so enforcement lives in the prompt; this just flags the input)
    if prestige_count(items) == 0:
        warnings.append("no prestige-outlet items in today's input")

    return critical, warnings


# --- self-test (no API needed) --------------------------------------------
if __name__ == "__main__":
    good_items = [
        {"source": "Reuters", "url": "https://example.com/a"},
        {"source": "WSJ", "url": "https://example.com/b"},
    ]
    good = (
        "**Some updates on the Iran war (8/10):**\n\n"
        "**US**\n"
        "- On Monday, the US [said](https://example.com/a) talks continued.\n"
        "- On Monday, an official [reported](https://example.com/b) a deal was near.\n"
        + "- On Tuesday, sources [told](https://example.com/a) reporters more.\n" * 12
    )
    crit, warn = validate_brief(good, good_items)
    assert not crit, f"expected clean, got critical: {crit}"

    stub = "**Some updates on the Iran war (8/10):**"
    crit, warn = validate_brief(stub, good_items)
    assert any("truncated" in c for c in crit), crit

    fabricated = good + "- On Wed, X [said](https://fake.example/z) something.\n"
    crit, warn = validate_brief(fabricated, good_items)
    assert any("not in the collected input" in c for c in crit), crit

    no_header = "US\n- On Monday, the US [said](https://example.com/a) x.\n" * 5
    crit, warn = validate_brief(no_header, good_items)
    assert any("header" in c for c in crit), crit

    # repair drops only the bullet(s) with unknown links, keeps the rest
    mixed = (
        "**Some updates on the Iran war (8/10):**\n"
        "- On Monday, the US [said](https://example.com/a) a real thing.\n"
        "- On Monday, X [said](https://fake.example/z) a fabricated thing.\n"
        "  - a sub-bullet under the bad item\n"
        "- On Tuesday, Y [reported](https://example.com/b) another real thing.\n"
    )
    repaired = repair_brief(mixed, good_items)
    assert "fake.example" not in repaired, repaired
    assert "sub-bullet under the bad item" not in repaired, repaired
    assert "example.com/a" in repaired and "example.com/b" in repaired, repaired

    print("validate.py self-test passed")
