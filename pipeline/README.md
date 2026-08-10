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
 ├─ collect.py    Google News RSS + outlet feeds + GDELT  → data/items_<date>.json + archive.db
 ├─ digest.py     Claude clusters, selects, formats        → out/brief_<date>.md
 │   └─ validate.py  checks the draft; regenerates on a stronger model if a CRITICAL check fails
 ├─ render.py     Markdown → Outlook-friendly HTML          → out/brief_<date>.html
 └─ deliver.py    emails the draft (Gmail or generic SMTP), or writes the file in local mode
```

### Failsafes (ported from the Korea/Japan digests)

`digest.py` runs a **validate-and-regenerate** loop. After each draft, `validate.py`
checks it, and a CRITICAL failure triggers a retry that escalates from the fast model to a
stronger one:

- **Stub guard** — rejects an empty or truncated brief.
- **SOURCE-OR-SKIP** — every linked URL must have appeared in the collected input; a link
  that wasn't in the input fails the brief (blocks fabricated links).
- **Header** — the brief must open with the house header line.
- **Prestige** — the formatter prompt requires strong outlets (WSJ, NYT, FT, Reuters, AP,
  Bloomberg, The Economist, WaPo, specialists) to be preferred when they reported a story.

If all retries fail, the tool repairs the last draft — dropping only the bullets with
unverifiable links — instead of failing the whole run. Warnings (item count outside 15–40,
use of "claim", no prestige outlet in the input) are logged but do not block delivery.

**Coverage:** `digest.py` interleaves candidates across the collection queries before the
`MAX_CANDIDATES` cap, so every region is represented instead of the cap being filled by the
first one or two queries. Add or retune queries in `collect.py`'s `GOOGLE_NEWS_QUERIES`.

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

With no email variables set, `deliver.py` runs in local mode: it writes
`out/brief_<date>.html` and prints the path for you to open and send yourself.

## Delivery

`deliver.py` supports two credential styles:

- **Gmail (matches the Korea/Japan digests):** set `GMAIL_USER`, `GMAIL_APP_PASS`, and
  `DIGEST_TO` (comma-separated recipients). Sends via Gmail SMTP SSL on port 465. Optional
  `GMAIL_FROM` overrides the From alias.
- **Generic SMTP:** set `SMTP_HOST`, `SMTP_USER`, `SMTP_PASS`, `REVIEWER_EMAIL`, and
  optionally `SMTP_PORT` (default 587, STARTTLS).

Gmail wins if both are present; if neither is, it falls back to local mode.

## Go live (GitHub Actions)

1. Put this `pipeline/` folder in a private GitHub repo.
2. Add repo **secrets**: `ANTHROPIC_API_KEY`, plus delivery credentials — either the Gmail
   set (`GMAIL_USER`, `GMAIL_APP_PASS`, `DIGEST_TO`) or the generic-SMTP set (`SMTP_HOST`,
   `SMTP_PORT`, `SMTP_USER`, `SMTP_PASS`, `REVIEWER_EMAIL`). Optionally set repo
   **variables** `IRAN_BRIEF_MODEL` and `IRAN_BRIEF_PRIMARY_MODEL`.
3. The workflow in `.github/workflows/iran-brief.yml` runs weekdays at 11:30 UTC (7:30 AM
   ET) and can also be triggered by hand from the Actions tab. It uploads the brief as a
   downloadable artifact and commits the SQLite archive so trends persist.

## Configuration

- **Sources:** edit `GOOGLE_NEWS_QUERIES`, `DIRECT_FEEDS`, and `KEYWORDS` in `collect.py`.
- **Models:** `IRAN_BRIEF_MODEL` is the fast first-attempt model (default `claude-sonnet-5`);
  `IRAN_BRIEF_PRIMARY_MODEL` is the stronger model used on a validation retry (default
  `claude-opus-4-8`).
- **Validation:** thresholds live in `validate.py` (`MIN_CHARS`, `MIN_ITEMS_CRITICAL`,
  the 12–25 target, the prestige list).
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
