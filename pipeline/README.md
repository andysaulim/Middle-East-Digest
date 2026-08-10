# Iran War Update: automated pipeline (v1)

Turns the hand-compiled daily tracker into a scheduled job. Every weekday morning it
collects the day's Iran-war news, has Claude cluster and format it into the house style,
and drops a ready-to-send draft in a reviewer's inbox. A human still glances and sends.

**Delivery mode:** auto-draft, you send. The pipeline emails the finished brief to one
reviewer, not to the team list.
**v1 sources:** free RSS + GDELT (no paid keys). Social (X) is a later add.

## Pipeline

```
run.py
 ├─ collect.py   Google News RSS + outlet feeds + GDELT  → data/items_<date>.json + archive.db
 ├─ digest.py    Claude clusters, selects, formats        → out/brief_<date>.md
 ├─ render.py    Markdown → Outlook-friendly HTML          → out/brief_<date>.html
 └─ deliver.py   emails the draft to REVIEWER_EMAIL (or writes the file in local mode)
```

Each file maps to a phase of the build plan and mirrors the Korea Daily Brief structure,
so this is a fork of a proven design, not a new invention.

## Run it locally

Dry run (collection only, no API key needed, proves the live feeds work):

```bash
python run.py --no-digest
```

Full run (needs an Anthropic key):

```bash
pip install -r requirements.txt
export ANTHROPIC_API_KEY=sk-ant-...
python run.py
```

With no SMTP variables set, `deliver.py` runs in local mode: it writes
`out/brief_<date>.html` and prints the path for you to open and send yourself.

## Go live (GitHub Actions)

1. Put this `pipeline/` folder in a private GitHub repo.
2. Add repo **secrets**: `ANTHROPIC_API_KEY`, `REVIEWER_EMAIL`, and for automated draft
   delivery `SMTP_HOST`, `SMTP_PORT`, `SMTP_USER`, `SMTP_PASS`. Optionally set repo
   **variable** `IRAN_BRIEF_MODEL`.
3. The workflow in `.github/workflows/iran-brief.yml` runs weekdays at 11:30 UTC (7:30 AM
   ET) and can also be triggered by hand from the Actions tab. It uploads the brief as a
   downloadable artifact and commits the SQLite archive so trends persist.

## Configuration

- **Sources:** edit `GOOGLE_NEWS_QUERIES`, `DIRECT_FEEDS`, and `KEYWORDS` in `collect.py`.
- **Model:** `IRAN_BRIEF_MODEL` env var (default `claude-sonnet-5`; use an Opus id for
  higher quality at higher cost).
- **House format:** the formatter rules live in `digest.py`'s `SYSTEM_PROMPT`, kept in sync
  with `../Iran War Update — Formatter Prompt.md`.
- **Schedule / send time:** the `cron` line in the workflow.

## The queryable archive (the payoff over an email thread)

Every item lands in `data/archive.db`. Once it accumulates you can ask the corpus questions
the old thread can't answer, e.g.:

```sql
SELECT collected_date, COUNT(*) FROM items WHERE title LIKE '%tanker%' GROUP BY 1;
```

That is what enables weekly rollups and trend lines (tanker attacks, Hormuz transits,
casualty tallies).

## Honest constraints (v1)

- **Human in the loop stays.** Auto-draft, not auto-send. The reviewer is the two-source
  gate before anything reaches the team.
- **No X/social yet.** CENTCOM, UKMTO, IDF, and named spokesmen need the paid X API or a
  manual watchlist. v1 ships without them; Google News surfaces much of it secondhand.
- **Flaky feeds degrade gracefully.** Some feeds block scripted requests (Al Arabiya
  returned 403 on the first run) and GDELT rate-limits; the collector logs and moves on.
- **Draft delivery via SMTP self-email** is the simple v1. A cleaner version creates a real
  Outlook draft in your mailbox through the Microsoft Graph API (`POST /me/messages`); swap
  that into `deliver.py` when you want it.

## Status

- `collect.py`: tested live, pulled 417 real Iran-war items on the first run.
- `render.py`: tested, produces clean Outlook-ready HTML.
- `digest.py` / `deliver.py`: written and ready; run once you add your Anthropic key
  (and SMTP creds for automated draft delivery).
