# Iran War Update — Setup & How It Works

A plain-language guide for the CSIS Middle East Program team. It explains what this tool
does, what arrives each morning, what the reviewer does, and the one-time setup an
administrator handles. No coding needed to read this.

## What it is

The Iran War Update is a daily brief on the Iran war, in the program's house style. Until
now it was hand-compiled. This tool automates the gathering and first-draft writing, so a
finished draft is waiting in a reviewer's inbox each weekday morning. **A person still
reviews and sends it** — nothing goes to the team automatically.

## What happens each morning

Every weekday around 7:30 AM ET, the tool runs on its own and:

1. **Collects** the last 24 hours of Iran-war news from free, public sources (Google News,
   Al Jazeera, Times of Israel, Al Arabiya, and the GDELT news database).
2. **Clusters and writes** the draft. It groups duplicate reports of the same event, drops
   opinion and filler, keeps the 12–25 genuinely significant developments, sorts them under
   the usual headers (US, Iran, Lebanon, Israel, Yemen / Saudi Arabia, Oman, General), and
   writes each as a one-line bullet with the source linked on the verb — the same format the
   brief has always used.
3. **Emails the draft** to one reviewer as a ready-to-send HTML email marked `[DRAFT]`.

## The reviewer's job

The reviewer is the quality gate. When the draft arrives:

1. **Glance through it** for anything off — a miscategorized item, a headline that reads
   wrong, a cluster that should or shouldn't be there.
2. **Check the sourcing.** Items resting on a single source for something load-bearing (a
   death toll, a strike, an official position) are tagged `[single-source]`. Confirm those
   before they go out, or drop them.
3. **Edit if needed, then forward** to the team distribution list.

That human check is deliberate and permanent. The tool drafts; a person decides.

## What it does *not* do (yet)

- **It does not send to the team by itself.** Only the reviewer does that.
- **No X / social feeds yet.** CENTCOM, UKMTO, IDF, and named spokesmen posts aren't pulled
  directly in this version; Google News surfaces much of it secondhand. Direct social is a
  planned add.
- **Some feeds are flaky.** A source that blocks automated requests or rate-limits is
  skipped for that run; the draft is built from whatever came through.

## The bonus: a searchable archive

Every item the tool collects is saved to a running archive. Over time that lets us answer
questions an email thread never could — for example, how tanker incidents or Strait of
Hormuz mentions trend week over week. This is what will power future weekly rollups.

## One-time setup (for the administrator)

This part is done once by whoever manages the GitHub repository. The tool runs on GitHub
Actions; no server to maintain.

1. **Add repository secrets** (Settings → Secrets and variables → Actions → *Secrets*):
   - `ANTHROPIC_API_KEY` — the Claude API key that powers the drafting step.
   - `REVIEWER_EMAIL` — where the morning draft is sent.
   - `SMTP_HOST`, `SMTP_PORT`, `SMTP_USER`, `SMTP_PASS` — the mail account the draft is sent
     from.
2. **Optional variable** (same page → *Variables*):
   - `IRAN_BRIEF_MODEL` — the Claude model to use. Leave unset for the sensible default.
3. **That's it.** The schedule (weekday mornings) is already built in.

Once the secrets are in, you can confirm it works without waiting for the morning run:
open the **Actions** tab, choose the **Iran War Update** workflow, and click **Run
workflow**. The draft email should arrive at `REVIEWER_EMAIL`, and the completed run also
keeps a downloadable copy of the brief under its **Artifacts**.

## Where to find things

- The finished brief for each run: the **Actions** tab → the run → **Artifacts**.
- The house-style rules the tool follows: `Iran War Update — Formatter Prompt.md`.
- Deeper technical detail: `pipeline/README.md`.

## Questions or changes

Want different sources, more or fewer items, a different send time, or a second reviewer?
Those are all quick configuration changes — pass the request to whoever manages the repo.
