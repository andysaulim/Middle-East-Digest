"""
history_data.py — Iran War Update, "This day in history" section

A short "on this day" note gives the brief historical context: the events on today's
calendar date, in past years, that shaped the U.S.–Iran and wider Middle East story. Like
calendar_data.py, this is a CURATED, hand-maintained list, never model-generated — a news
product must not invent history. The section renders only the entries whose month/day match
today; on a date with no entry it renders nothing.

Entry format: a dict keyed by (month, day) -> list of (year, "label"), e.g.
    (11, 4): [(1979, "Iranian students seized the U.S. embassy in Tehran ...")]
Keep labels factual and neutral, and keep to well-established, verifiable events.

Stdlib only.
"""

from datetime import date

# --- Curated "on this day" entries. EDIT ME. --------------------------------
EVENTS = {
    (1, 3): [(2020, "A U.S. drone strike at Baghdad airport killed IRGC Quds Force commander Qassem Soleimani.")],
    (1, 8): [(2020, "Iran fired ballistic missiles at the al-Asad and Erbil bases in Iraq in reprisal for Soleimani; hours later the IRGC mistakenly shot down Ukraine International Airlines Flight 752.")],
    (1, 16): [(1979, "Shah Mohammad Reza Pahlavi left Iran, days before the revolution's victory.")],
    (1, 20): [(1981, "Iran released the 52 U.S. embassy hostages after 444 days, minutes after Ronald Reagan's inauguration.")],
    (2, 1): [(1979, "Ayatollah Ruhollah Khomeini returned to Tehran from exile in France.")],
    (2, 11): [(1979, "The Iranian Revolution triumphed as the monarchy fell; the date is marked annually as the anniversary of the Islamic Revolution.")],
    (4, 7): [(2019, "The United States designated Iran's Islamic Revolutionary Guard Corps a Foreign Terrorist Organization, the first such designation of a state military.")],
    (4, 18): [(1983, "A suicide bombing at the U.S. embassy in Beirut killed 63 people; Iran-backed groups were implicated.")],
    (5, 8): [(2018, "President Trump announced the U.S. withdrawal from the JCPOA, the 2015 Iran nuclear deal, and the reimposition of sanctions.")],
    (7, 3): [(1988, "The USS Vincennes shot down Iran Air Flight 655 over the Persian Gulf, killing all 290 aboard.")],
    (7, 14): [(2015, "Iran and the P5+1 reached the Joint Comprehensive Plan of Action (JCPOA) in Vienna.")],
    (7, 20): [(1987, "The U.N. Security Council adopted Resolution 598, the basis for the 1988 ceasefire in the Iran-Iraq War.")],
    (8, 19): [(1953, "A coup backed by the U.S. CIA and Britain's MI6 (Operation Ajax) overthrew Iran's elected prime minister, Mohammad Mossadegh.")],
    (9, 16): [(2022, "The death in custody of Mahsa Amini touched off nationwide protests across Iran.")],
    (9, 22): [(1980, "Iraq invaded Iran, beginning the eight-year Iran-Iraq War.")],
    (10, 7): [(2023, "A Hamas assault on southern Israel killed about 1,200 people and triggered the war in Gaza, reshaping the regional confrontation with Iran and its allies.")],
    (10, 23): [(1983, "A suicide truck bombing killed 241 U.S. service members at the Marine barracks in Beirut; the U.S. attributed it to Iran-backed Hezbollah.")],
    (11, 4): [(1979, "Iranian students seized the U.S. embassy in Tehran, beginning the 444-day hostage crisis.")],
    (12, 27): [(2007, "A U.S. National Intelligence Estimate assessed that Iran had halted its nuclear weapons design work in 2003, reshaping the policy debate.")],
    (6, 13): [(2025, "Israel launched a wide air campaign against Iranian nuclear and military targets, opening the June 2025 Israel-Iran war.")],
}


def render_section(today=None):
    """Markdown for "This day in history", or "" when there is no entry for today."""
    if today is None:
        today = date.today()
    entries = EVENTS.get((today.month, today.day))
    if not entries:
        return ""
    lines = ["**This day in history**"]
    for year, label in sorted(entries):
        lines.append(f"- {year}: {label}")
    return "\n".join(lines)


if __name__ == "__main__":
    # A date we know has an entry.
    out = render_section(date(2026, 11, 4))
    assert out.startswith("**This day in history**"), out
    assert "1979:" in out and "hostage" in out, out
    # Multi-source date sorts by year.
    assert render_section(date(2026, 1, 3)).count("- ") == 1
    # A date with no entry renders nothing.
    assert render_section(date(2026, 6, 1)) == ""
    print(render_section(date(2026, 5, 8)))
    print("\nhistory_data.py self-test passed")
