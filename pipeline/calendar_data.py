"""
calendar_data.py — Iran War Update, "Dates ahead" section

Flags upcoming dates the team should have on the radar — anniversaries that tend to draw
statements or attacks, plus current diplomatic deadlines, negotiation rounds, truces, and
scheduled meetings. Renders the ones falling in the next ~60 days as a "Dates ahead" section.

Three sources:
  1. DATES / ONE_OFFS below — curated recurring anniversaries and known institutional dates.
  2. LUNAR (computed) — the major Islamic observances (Ashura, Arbaeen, Ramadan, Eid, and
     Quds Day) that shift ~11 days a year. These used to need a manual entry every year; now
     they are computed with the arithmetic Islamic calendar and always appear, flagged
     APPROXIMATE (the true date is set locally by moon-sighting). A precise editor entry in
     key_dates.json within a couple of days suppresses the computed one.
  3. data/key_dates.json — an EDITABLE file where the editor drops current, war-specific
     dates (a negotiation deadline, a ceasefire review, an IAEA session, an announced round
     of talks): a list of {"date": "YYYY-MM-DD", "label": "..."}. This is how deadlines /
     truces / negotiations reach the brief, since those are event-driven and can't be known
     in advance. Add a line as soon as a date is announced in the news.

A news product must not invent a specific event, so the curated and editor entries stay
hand-verified; the computed lunar dates are recurring observances, not events, and are
labelled approximate.

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
    (7, 12, "Anniversary of the start of the 2006 Israel-Hezbollah war.", True),
    (7, 14, "Anniversary of the 2015 signing of the JCPOA (Iran nuclear deal).", True),
    (8, 20, "Anniversary of the 1988 ceasefire that ended the Iran-Iraq War.", True),
    (9, 22, "Anniversary of the 1980 start of the Iran-Iraq War.", True),
    (10, 7, "Anniversary of the 2023 Hamas attack on Israel that reshaped the regional war.", True),
    (11, 4, "Anniversary of the 1979 seizure of the U.S. embassy in Tehran.", True),
    (11, 27, "Anniversary of the 2020 assassination of Iranian nuclear scientist Mohsen Fakhrizadeh.", True),
]

# --- Islamic (lunar) observances, computed automatically ---------------------
# These shift ~11 days earlier each Gregorian year and used to require a manual key_dates.json
# entry every year. We compute them with the arithmetic ("tabular") Islamic calendar so they
# always appear; the true date is set by moon-sighting (Iran runs its own), so each is flagged
# APPROXIMATE and a precise editor entry within a couple of days suppresses the computed one.
_ISLAMIC_EPOCH = 1948439                      # tabular civil epoch matching the usual observance
_APPROX = " (approximate; lunar, set locally by moon-sighting)"

# (hijri_month, hijri_day, label)
LUNAR = [
    (1, 10, "Ashura, a major Shia observance that draws large gatherings in Iran and among "
            "Iran-aligned groups; a frequent occasion for statements."),
    (2, 20, "Arbaeen, the mass Shia pilgrimage to Karbala; a large Iran-Iraq movement of pilgrims."),
    (9, 1, "Start of Ramadan."),
    (10, 1, "Eid al-Fitr (end of Ramadan)."),
    (12, 10, "Eid al-Adha."),
]


def _hijri_to_gregorian(iy, im, idd):
    """Arithmetic (tabular) Hijri date -> Gregorian date. Accurate to about a day versus the
    sighting-based observance, which is all a heads-up 'dates ahead' entry needs."""
    jd = int((11 * iy + 3) / 30) + 354 * iy + 30 * im - int((im - 1) / 2) + idd + _ISLAMIC_EPOCH - 385
    l = jd + 68569
    n = (4 * l) // 146097
    l = l - (146097 * n + 3) // 4
    i = (4000 * (l + 1)) // 1461001
    l = l - (1461 * i) // 4 + 31
    j = (80 * l) // 2447
    day = l - (2447 * j) // 80
    l = j // 11
    month = j + 2 - 12 * l
    year = 100 * (n - 49) + i + l
    return date(year, month, day)


def _lunar_upcoming(today, horizon, manual_dates=()):
    """Islamic observances (fixed + Quds Day) whose computed Gregorian date lands in the window.
    A computed date within 2 days of an editor-supplied key_dates entry is skipped, so a precise
    manual date always wins over the approximation."""
    base = today.year - 579                    # rough Hijri year for a Gregorian year
    out = []

    def _add(d, label):
        if today <= d <= horizon and not any(abs((d - md).days) <= 2 for md in manual_dates):
            out.append((d, label + _APPROX))

    for hy in range(base - 1, base + 2):
        for hm, hd, label in LUNAR:
            try:
                _add(_hijri_to_gregorian(hy, hm, hd), label)
            except (ValueError, OverflowError):
                continue
        # Quds Day: the last Friday of Ramadan (Iran holds major state rallies).
        try:
            ramadan_end = _hijri_to_gregorian(hy, 10, 1) - timedelta(days=1)
            quds = ramadan_end - timedelta(days=(ramadan_end.weekday() - 4) % 7)
            _add(quds, "Quds Day, when Iran holds major state rallies (last Friday of Ramadan).")
        except (ValueError, OverflowError):
            pass
    return out

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
    manual = [(d, label) for d, label in _from_key_dates() if today <= d <= horizon]
    out += manual
    # Computed lunar observances, suppressed when the editor supplied a precise nearby date.
    out += _lunar_upcoming(today, horizon, manual_dates=[d for d, _ in manual])
    # De-duplicate identical (date, label) pairs, then order soonest first.
    seen, deduped = set(), []
    for d, label in out:
        key = (d, label)
        if key not in seen:
            seen.add(key)
            deduped.append((d, label))
    deduped.sort(key=lambda t: t[0])
    return deduped


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

    # Hijri conversion lands within a day of the known observance (tabular vs. sighting).
    assert _hijri_to_gregorian(1447, 1, 10) == date(2025, 7, 5), _hijri_to_gregorian(1447, 1, 10)
    # Ramadan 1447 begins ~2026-02-17, so a February 2026 window auto-surfaces Ramadan (no
    # manual key_dates entry needed) and flags it approximate.
    feb = [lbl for _, lbl in upcoming(date(2026, 2, 1), within_days=40)]
    assert any("Ramadan" in x and "approximate" in x for x in feb), feb
    # A precise editor entry within 2 days suppresses the computed duplicate.
    from_ram = date(2026, 2, 17)
    assert not _lunar_upcoming(date(2026, 2, 1), date(2026, 3, 20),
                               manual_dates=[from_ram]) or all(
        abs((d - from_ram).days) > 2 or "Ramadan" not in lbl
        for d, lbl in _lunar_upcoming(date(2026, 2, 1), date(2026, 3, 20), manual_dates=[from_ram]))
    print("\ncalendar_data.py self-test passed")
