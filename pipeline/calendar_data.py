"""
calendar_data.py — Iran War Update, "Dates ahead" section

Flags upcoming dates the team should have on the radar — anniversaries that tend to draw
statements or attacks, plus current diplomatic deadlines, negotiation rounds, truces, and
scheduled meetings. Renders the ones falling in the next ~60 days as a "Dates ahead" section.

Two sources, both hand-maintained on purpose (a news product must not invent a date):
  1. DATES / ONE_OFFS below — recurring anniversaries and known institutional dates.
  2. data/key_dates.json — an EDITABLE file where the editor drops current, war-specific
     dates (a negotiation deadline, a ceasefire review, an IAEA session, an announced round
     of talks): a list of {"date": "YYYY-MM-DD", "label": "..."}. This is how deadlines /
     truces / negotiations reach the brief, since those are event-driven and can't be known
     in advance. Add a line as soon as a date is announced in the news.

Stdlib only.
"""

import json
from datetime import date, datetime, timedelta
from pathlib import Path

DATA_DIR = Path(__file__).parent / "data"
HORIZON_DAYS = 60

# --- Curated recurring anniversaries. EDIT ME. -------------------------------
# Well-established, verifiable dates. Lunar/Islamic-calendar observances (Ashura, Arbaeen,
# Quds Day, Ramadan) shift ~11 days a year — add those to data/key_dates.json each year.
DATES = [
    # (month, day, label, recurring)
    (1, 3, "Anniversary of the 2020 U.S. strike that killed Qassem Soleimani in Baghdad.", True),
    (1, 8, "Anniversary of Iran's 2020 ballistic-missile strike on U.S. forces at al-Asad air base in Iraq.", True),
    (1, 20, "Anniversary of the 1981 release of the 52 U.S. embassy hostages after 444 days.", True),
    (2, 11, "Anniversary of the 1979 Islamic Revolution; large state rallies are held across Iran.", True),
    (3, 20, "Nowruz, the Iranian New Year.", True),
    (4, 1, "Islamic Republic Day in Iran.", True),
    (5, 8, "Anniversary of the 2018 U.S. withdrawal from the JCPOA.", True),
    (6, 13, "Anniversary of the June 2025 Israel-Iran war.", True),
    (7, 3, "Anniversary of the 1988 U.S. downing of Iran Air Flight 655 over the Gulf.", True),
    (7, 14, "Anniversary of the 2015 signing of the JCPOA (Iran nuclear deal).", True),
    (9, 22, "Anniversary of the 1980 start of the Iran-Iraq War.", True),
    (10, 7, "Anniversary of the 2023 Hamas attack on Israel that reshaped the regional war.", True),
    (11, 4, "Anniversary of the 1979 seizure of the U.S. embassy in Tehran.", True),
]

# One-off institutional dates with an explicit year (auto-expire once past).
# Format: (year, month, day, "label"). IAEA Board of Governors meets roughly quarterly
# (Mar, Jun, Sep, Nov); add each session with its real dates when the schedule is published.
ONE_OFFS = [
    (2026, 9, 22, "U.N. General Assembly general debate opens in New York (heads-of-state week)."),
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


def _from_key_dates():
    """Editor-supplied current dates from data/key_dates.json -> [(date, label)]."""
    path = DATA_DIR / "key_dates.json"
    if not path.exists():
        return []
    out = []
    try:
        for e in json.loads(path.read_text(encoding="utf-8")):
            try:
                d = datetime.strptime(e["date"].strip(), "%Y-%m-%d").date()
            except (KeyError, ValueError, AttributeError):
                continue
            label = (e.get("label") or "").strip()
            if label:
                out.append((d, label))
    except Exception as exc:
        print(f"  [calendar] key_dates.json ERR: {exc!r}")
    return out


def upcoming(today=None, within_days=HORIZON_DAYS):
    """Curated + editor-supplied dates in [today, today+within_days], soonest first."""
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
    for d, label in _from_key_dates():
        if today <= d <= horizon:
            out.append((d, label))
    out.sort(key=lambda t: t[0])
    return out


def render_section(today=None, within_days=HORIZON_DAYS):
    """Markdown for the "Dates ahead" section, or "" when nothing is upcoming."""
    items = upcoming(today, within_days)
    if not items:
        return ""
    lines = ["**Dates ahead**"]
    for d, label in items:
        lines.append(f"- {d.month}/{d.day}: {label}")
    return "\n".join(lines)


if __name__ == "__main__":
    ref = date(2026, 6, 1)
    print(f"From {ref} (next {HORIZON_DAYS} days):\n")
    print(render_section(ref) or "(nothing upcoming)")
    assert upcoming(date(2026, 6, 1)), "expected the 6/13 anniversary within the horizon"
    assert not upcoming(date(2026, 6, 1), within_days=1), "expected nothing within 1 day"
    # July window should now catch the added 7/3 (Flight 655) and 7/14 (JCPOA) anniversaries
    jul = [lbl for _, lbl in upcoming(date(2026, 7, 1), within_days=20)]
    assert any("Flight 655" in x for x in jul) and any("JCPOA" in x for x in jul), jul
    print("\ncalendar_data.py self-test passed")
