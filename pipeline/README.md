# Iran War Update: automated pipeline (v1)

Turns the hand-compiled daily tracker into a scheduled job. Every weekday morning it
collects the day's Iran-war news, has Claude cluster and format it into the house style,
and drops a ready-to-send draft in a reviewer's inbox. A human still glances and sends.

**Delivery mode:** auto-draft, you send. The pipeline emails the finished brief to one
reviewer, not to the team list.
**Sources:** free RSS + Google News + Al Jazeera live blog + GDELT (no paid keys). Primary
social (X, Truth Social) comes in through a manual injection file until a paid API is added.

## Pipeline

```
run.py                                                     (daily brief)
 ├─ collect.py    Google News RSS + Al Jazeera live blog + outlet feeds + GDELT + social + manual
 │   ├─ resolve.py   turns Google News redirect links into real publisher URLs (cached)
 │   └─ social.py    pulls X (syndication) + Truth Social (Mastodon API), no paid key
 │                                                        → data/items_<date>.json + archive.db
 ├─ digest.py     Claude clusters, selects, formats        → out/brief_<date>.md
 │   ├─ validate.py     checks the draft; regenerates on a stronger model if a CRITICAL check fails
 │   └─ closing sections (appended from source, never the model):
 │        congress.py (Iran bills via api.congress.gov) + history_data.py ("This day in
 │        history") + calendar_data.py ("Dates ahead")
 ├─ render.py     Markdown → Outlook-friendly HTML          → out/brief_<date>.html
 └─ deliver.py    Outlook draft (Graph) / Gmail / SMTP, or writes the file in local mode

weekly.py                                                  (Friday Week in Review)
 └─ reads data/archive.db → Claude synthesizes the week + factual tallies → render → deliver
```

### Collection window

1 day on Tuesday–Friday; **3 days on Monday** so the Monday brief carries the weekend
(Saturday, Sunday, and Monday morning up to the ~7am ET send). After a holiday, set the
`LOOKBACK_DAYS` env var to widen the window for one run.

### Sources and how to extend them

- **Google News RSS** — the relevance engine; edit `GOOGLE_NEWS_QUERIES` in `collect.py`.
  Its links are opaque redirects, so `resolve.py` canonicalizes them to the real publisher
  URL (e.g. `reuters.com`, `aje.news`). That both fixes the SOURCE-OR-SKIP validator (the
  model can copy a short link accurately) and gives the email clean, house-style links.
- **Al Jazeera** — the human tracker's backbone. `collect.py` scrapes the Middle East
  section and live blog for canonical article links (the plain AJ RSS feed is too thin).
- **Direct feeds** — Times of Israel, Al Arabiya (keyword-filtered). A browser User-Agent
  lifts most of the 403s these gave v1; a `site:` Google News query is the fallback.
- **GDELT** — event backbone; rate-limits, so it retries and degrades gracefully.
- **Social (`social.py`)** — pulls the watchlist automatically from free, no-account
  endpoints: **X** via the syndication timeline (`syndication.twimg.com`, the embed feed)
  and **Truth Social** via its Mastodon-compatible API (unauthenticated viewing still works
  for allowed accounts like Trump). Edit `X_HANDLES` / `TRUTH_SOCIAL_ACCOUNTS` in
  `social.py`. Both are unsupported endpoints and may `403` from a datacenter IP; on failure
  they degrade to the manual file. Disable with `SOCIAL_FEEDS=0`.
- **Manual injection** — the always-there fallback: drop items no scraper reaches into
  `data/manual.json` (standing) or `data/manual_<date>.json` (today only), as a list of
  `{"source","title","url"}`.

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

**Every section, every day:** after validation, `digest.py` guarantees all standard
headers are present in a fixed order — the human tracker's six: US, Iran, Lebanon, Israel,
Saudi Arabia/Yemen/Iraq (one combined Gulf/Iraq header), and General. Other countries
(Oman, Egypt, Jordan, Syria, Caspian) fold into General or the combined header via
`_ALIASES`. A section with no news shows `Nothing to Report.` rather than disappearing, so
the reader can tell "quiet" from "missed." Edit `CATEGORIES` / `_ALIASES` in `digest.py`.

**Dates ahead:** `calendar_data.py` holds a curated list of upcoming anniversaries and
deadlines and appends the ones falling in the next ~45 days as a "Dates ahead" section.
It is deliberately hand-maintained (not model-generated) so the brief never invents a
date — edit `DATES` / `ONE_OFFS` there.

**Weekly rollup (`weekly.py`):** a separate Friday job reads the archive for the last seven
days, computes factual tallies (strikes, tanker/maritime incidents, casualties, Hormuz,
Houthi/Red Sea, nuclear, Hezbollah/Lebanon), and has Claude synthesize the week's arc in
house style. An exact "By the numbers this week" block is appended deterministically. Runs
via `.github/workflows/iran-weekly.yml` (Friday 21:00 UTC) or `python weekly.py`.

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

`deliver.py` supports three credential styles, tried in this order:

- **Outlook / Microsoft Graph** (nicest UX — a real editable draft in the mailbox): set
  `MS_TENANT_ID`, `MS_CLIENT_ID`, `MS_CLIENT_SECRET`, `MS_MAILBOX`. Requires CSIS IT to
  register an Entra app with the `Mail.ReadWrite` application permission (see SETUP.md §11).
  If Graph is configured but errors, delivery falls through to Gmail rather than failing.
- **Gmail (matches the Korea/Japan digests):** set `GMAIL_USER`, `GMAIL_APP_PASS`, and
  `DIGEST_TO` (comma-separated recipients). Sends via Gmail SMTP SSL on port 465. Optional
  `GMAIL_FROM` overrides the From alias.
- **Generic SMTP:** set `SMTP_HOST`, `SMTP_USER`, `SMTP_PASS`, `REVIEWER_EMAIL`, and
  optionally `SMTP_PORT` (default 587, STARTTLS).

The first fully-configured style wins; if none is, it falls back to local mode.

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
- **Social is semi-manual.** CENTCOM, UKMTO, IDF, named spokesmen, and Trump (Truth
  Social) need the paid X API for full automation. Until then, an editor drops the key
  primary posts into `data/manual.json` and the pipeline folds them in; Google News and Al
  Jazeera surface much of the rest secondhand.
- **URL resolution is best-effort.** `resolve.py` calls Google to canonicalize redirect
  links; if Google rate-limits, links fall back to the (working, if ugly) redirect and the
  run still ships. Disable with `RESOLVE_URLS=0`.
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
