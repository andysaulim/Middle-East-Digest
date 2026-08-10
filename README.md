# Middle East Digest

Automated pipeline for the CSIS Middle East Program's daily **Iran War Update**.
Every weekday morning it collects the day's Iran-war news from free sources, has Claude
cluster and format it into the program's house style, and drops a ready-to-send draft in a
reviewer's inbox. A human still glances at it and sends. This is a fork of the proven Korea
Daily Brief design, adapted to the Iran/Middle East beat.

## Repository layout

```
.
├── .github/workflows/iran-brief.yml   Scheduled + on-demand GitHub Actions run
├── Iran War Update — Formatter Prompt.md   House-style spec (human-readable source of truth)
├── pipeline/
│   ├── run.py         Orchestrator: collect -> digest -> render -> deliver
│   ├── collect.py     Google News RSS + outlet feeds + GDELT  -> data/items_<date>.json + archive.db
│   ├── digest.py      Claude clusters, selects, formats        -> out/brief_<date>.md
│   ├── render.py      Markdown -> Outlook-friendly HTML         -> out/brief_<date>.html
│   ├── deliver.py     Emails the draft to REVIEWER_EMAIL (or writes the file in local mode)
│   ├── requirements.txt
│   ├── README.md      Full pipeline documentation
│   └── data/          SQLite archive + dated JSON snapshots
```

The detailed pipeline docs, configuration knobs, and honest v1 constraints live in
[`pipeline/README.md`](pipeline/README.md). The house-style formatting rules live in
[`Iran War Update — Formatter Prompt.md`](Iran%20War%20Update%20%E2%80%94%20Formatter%20Prompt.md)
and are mirrored in `pipeline/digest.py`'s `SYSTEM_PROMPT` — keep the two in sync.

## Quick start (local)

Dry run (collection only, no API key needed, proves the live feeds work):

```bash
cd pipeline
python run.py --no-digest
```

Full run (needs an Anthropic key):

```bash
cd pipeline
pip install -r requirements.txt
export ANTHROPIC_API_KEY=sk-ant-...
python run.py
```

With no SMTP variables set, `deliver.py` runs in local mode: it writes
`out/brief_<date>.html` and prints the path for you to open and send yourself.

## Scheduled run (GitHub Actions)

The workflow at [`.github/workflows/iran-brief.yml`](.github/workflows/iran-brief.yml) runs
weekdays at 11:30 UTC (7:30 AM ET during EDT) and can also be triggered by hand from the
**Actions** tab. Each run uploads the brief as a downloadable artifact and commits the
SQLite archive so trends persist.

For scheduled runs to deliver drafts, add these repository **secrets**:

| Secret | Purpose |
| --- | --- |
| `ANTHROPIC_API_KEY` | Required. Powers the digest/formatting step. |
| `REVIEWER_EMAIL` | Recipient of the drafted brief. |
| `SMTP_HOST`, `SMTP_PORT`, `SMTP_USER`, `SMTP_PASS` | SMTP credentials for automated draft delivery. |

Optionally set the repository **variable** `IRAN_BRIEF_MODEL` to override the model (default
`claude-sonnet-5`; use an Opus id for higher quality at higher cost). Without the SMTP
secrets a scheduled run still builds and archives the brief; it just falls back to local
mode instead of emailing it.

## The queryable archive

Every collected item lands in `pipeline/data/archive.db`. Once it accumulates you can ask
the corpus questions an email thread can't answer, e.g.:

```sql
SELECT collected_date, COUNT(*) FROM items WHERE title LIKE '%tanker%' GROUP BY 1;
```

That is what enables weekly rollups and trend lines (tanker attacks, Hormuz transits,
casualty tallies).

## Status

- `collect.py`: tested live, pulled 417 real Iran-war items on the first run.
- `render.py`: tested, produces clean Outlook-ready HTML.
- `digest.py` / `deliver.py`: written and ready; run once you add your Anthropic key
  (and SMTP creds for automated draft delivery).
- Workflow: scheduled weekday run + manual dispatch, artifact upload, archive commit.
