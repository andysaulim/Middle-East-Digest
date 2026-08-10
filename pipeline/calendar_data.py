"""
calendar_data.py — Iran War Update, "Dates ahead" section

The human tracker sometimes flags upcoming dates the team should have on the radar:
diplomatic deadlines, anniversaries that tend to draw statements or attacks, scheduled
meetings. This module holds a CURATED list of such dates and renders the ones falling in
the next few weeks as a "Dates ahead" section appended to the brief.

This is deliberately NOT model-generated: a news product must not invent dates, so the
list is hand-maintained here and simply filtered by "is it coming up soon." Edit `DATES`
to add, remove, or correct entries.

Entry format:
    (month, day, "label", recurring)
      month, day : integers (the calendar date)
      label      : what to show
      recurring  : True  -> an annual anniversary (year is computed automatically)
                   False -> a one-off; put the real year in the label and set an
                            explicit `year=` so it drops off after it passes

Stdlib only.
"""

from datetime import date, timedelta

# --- Curated dates. EDIT ME. -------------------------------------------------
# Keep to well-established, verifiable dates. Lunar/Islamic-calendar observances
# (Ashura, Arbaeen, Ramadan) shift ~11 days a year, so add them as one-offs with the
# correct year rather than as recurring entries.
DATES = [
    # (month, day, label, recurring)
    (1, 3, "Anniversary of the 2020 U.S. strike that killed Qassem Soleimani in Baghdad.", True),
    (3, 20, "Nowruz, the Iranian New Year.", True),
    (4, 1, "Islamic Republic Day in Iran.", True),
    (6, 13, "Anniversary of the June 2025 Israel-Iran war.", True),
    (7, 14, "Anniversary of the 2015 signing of the JCPOA (Iran nuclear deal).", True),
    (11, 4, "Anniversary of the 1979 seizure of the U.S. embassy in Tehran.", True),
]

# One-off dates with an explicit year live here (auto-expire once past).
# Format: (year, month, day, "label")
ONE_OFFS = [
    # (2026, 9, 15, "U.N. General Assembly high-level week opens in New York."),
]


def _next_occurrence(month, day, today):
    """The next date with this month/day on or after `today` (this year or next)."""
    year = today.year
    try:
        d = date(year, month, day)
    except ValueError:
        return None  # e.g. Feb 29 in a non-leap year; skip
    if d < today:
        try:
            d = date(year + 1, month, day)
        except ValueError:
            return None
    return d


def upcoming(today=None, within_days=45):
    """Return curated dates in [today, today+within_days], each as (date, label),
    sorted soonest first."""
    if today is None:
        today = date.today()
    horizon = today + timedelta(days=within_days)
    out = []
    for month, day, label, recurring in DATES:
        d = _next_occurrence(month, day, today) if recurring else None
        if d and today <= d <= horizon:
            out.append((d, label))
    for year, month, day, label in ONE_OFFS:
        try:
            d = date(year, month, day)
        except ValueError:
            continue
        if today <= d <= horizon:
            out.append((d, label))
    out.sort(key=lambda t: t[0])
    return out


def render_section(today=None, within_days=45):
    """Markdown for the "Dates ahead" section, or "" when nothing is upcoming."""
    items = upcoming(today, within_days)
    if not items:
        return ""
    lines = ["**Dates ahead**"]
    for d, label in items:
        lines.append(f"- {d.month}/{d.day}: {label}")
    return "\n".join(lines)


if __name__ == "__main__":
    # Show what would render from a fixed reference date (no live clock needed).
    ref = date(2026, 6, 1)
    print(f"From {ref} (next 45 days):\n")
    print(render_section(ref) or "(nothing upcoming)")
    assert upcoming(date(2026, 6, 1)), "expected the 6/13 anniversary within 45 days"
    assert not upcoming(date(2026, 6, 1), within_days=1), "expected nothing within 1 day"
    print("\ncalendar_data.py self-test passed")
