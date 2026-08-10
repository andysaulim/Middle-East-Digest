# Iran War Update — Full Explainer and Setup Guide

A complete, plain-language guide to the automated Iran War Update for the CSIS Middle East
Program. It explains why the tool exists, exactly how it builds the brief each morning, what
the reviewer and administrator each do, what it deliberately does not do yet, and how to run,
test, configure, and troubleshoot it. No coding knowledge is needed to read this document;
the one section aimed at a technical administrator is clearly marked.

---

## Contents

1. [What this is, in one paragraph](#1-what-this-is-in-one-paragraph)
2. [Why we built it](#2-why-we-built-it)
3. [The big picture: what happens each morning](#3-the-big-picture-what-happens-each-morning)
4. [How the brief is built, stage by stage](#4-how-the-brief-is-built-stage-by-stage)
5. [The house style the tool follows](#5-the-house-style-the-tool-follows)
6. [Where the news comes from](#6-where-the-news-comes-from)
7. [The reviewer's role](#7-the-reviewers-role)
8. [The searchable archive and what it unlocks](#8-the-searchable-archive-and-what-it-unlocks)
9. [What it does not do yet, and the roadmap](#9-what-it-does-not-do-yet-and-the-roadmap)
10. [Who does what](#10-who-does-what)
11. [Administrator setup (one time)](#11-administrator-setup-one-time)
12. [Running and testing it](#12-running-and-testing-it)
13. [Troubleshooting and FAQ](#13-troubleshooting-and-faq)
14. [Cost, privacy, and data handling](#14-cost-privacy-and-data-handling)
15. [Where to find things](#15-where-to-find-things)
16. [Requesting changes](#16-requesting-changes)

---

## 1. What this is, in one paragraph

The Iran War Update is the program's daily brief on the Iran war, in the same house style it
has always used. Until now a person compiled it by hand every morning: reading the wires,
grouping duplicate reports, choosing what mattered, and writing it up. This tool automates the
gathering and the first draft, so a finished draft is waiting in a reviewer's inbox each
weekday morning. **A person still reviews and sends it.** Nothing reaches the team
automatically. Think of the tool as a very fast research assistant that produces a solid first
draft; the reviewer remains the editor and the final word.

## 2. Why we built it

Three reasons.

- **Time.** Compiling the brief by hand took a chunk of every morning. The tool does the
  collection and first pass in a couple of minutes, so the human effort shifts from assembling
  to checking.
- **Consistency.** The formatting, categories, sourcing rules, and neutral-verb style are now
  applied the same way every day, written down and enforced, rather than living only in one
  person's habits.
- **A memory.** Everything the tool collects is saved to a running archive. An email thread
  cannot answer "how many tanker incidents did we log this month?" A structured archive can.
  That is the foundation for future weekly rollups and trend lines.

This is not a new invention. It is a fork of the proven Korea Daily Brief pipeline, adapted to
the Iran and wider Middle East beat, so the design is already road-tested.

## 3. The big picture: what happens each morning

Every weekday at about 7:30 AM Eastern, without anyone doing anything, the tool:

1. **Collects** the last 24 hours of Iran-war news from free, public sources.
2. **Clusters and writes** a draft: it groups duplicate reports of the same event, drops
   opinion and filler, keeps the genuinely significant developments, sorts them under the
   usual headers, and writes each as a one-line bullet with the source linked on the verb.
3. **Formats** the draft as a clean, Outlook-friendly HTML email.
4. **Delivers** it to one reviewer as a ready-to-send draft marked `[DRAFT]`.

The reviewer glances at it, edits if needed, and forwards it to the team. Total human time is
a few minutes instead of an hour.

## 4. How the brief is built, stage by stage

Under the hood the tool runs four steps in order. You do not need to operate these; this is
just so the team understands what is happening.

**Step 1 — Collect.** The tool queries several free news sources for the last 24 hours (see
[Section 6](#6-where-the-news-comes-from)), pulls back the day's candidate articles, removes
duplicates by matching similar headlines, and saves the result both as the day's working list
and into the permanent archive. A typical run gathers a few hundred raw articles that collapse
to a smaller deduplicated set. If a source is temporarily unavailable, the tool notes it and
moves on rather than failing.

**Step 2 — Digest (the drafting).** The deduplicated list is handed to Claude (Anthropic's AI
model) together with the program's house-style instructions. In one pass the model clusters
articles that describe the same event, decides what is significant enough to include, sorts
each item into the correct regional header, writes it in the house one-bullet format, links
the source on the reporting verb, and flags anything that rests on a single source. The model
is instructed to use only the article links actually present in the day's list and never to
invent a link or an event.

**Step 3 — Render.** The drafted brief is converted from plain text into a tidy HTML email
that mirrors the tracker's familiar look: bold category headers, bulleted items, indented
sub-bullets for quotes or follow-on detail, and source links on the verb. It is built to
render cleanly in Outlook.

**Step 4 — Deliver.** The HTML brief is emailed to the reviewer with the subject line
`[DRAFT] Iran War Update (M/D)`. If email is not configured, the tool instead saves the file
and a copy is attached to the run so someone can open and send it manually (see
[Section 12](#12-running-and-testing-it)).

## 5. The house style the tool follows

The tool is not writing freely. It follows an explicit style specification (the file
`Iran War Update — Formatter Prompt.md` in the repository). The key rules:

- **Categories, in this fixed order**, omitting any that are empty: US, Iran, Lebanon, Israel,
  Yemen / Saudi Arabia, Oman, General.
- **One bullet per item**, phrased as "On [Weekday], [actor] [verb] [what happened]."
- **The source link sits on the reporting verb** (for example, the word "said" or "reported"
  becomes the hyperlink).
- **Neutral verbs only:** said, reported, wrote, announced, told, confirmed, warned. The tool
  is told never to use "claim" in a way that implies doubt.
- **Sourcing discipline.** If two or more independent outlets report the same event, it is
  treated as corroborated and the strongest source is linked. If an item rests on a single
  source and is load-bearing (a death toll, a strike, an official position), it is tagged
  `[single-source]` so the reviewer knows to double-check it.
- **Selectivity.** The tool aims for roughly 12 to 25 items across the whole brief, not
  everything it found. Opinion pieces, explainers, and trivia are dropped.
- **Mechanics:** U.S. and U.K. keep their periods, percentages are spelled out ("42 percent"),
  the serial comma is used, specific figures are given as numerals, and em-dashes are avoided.

Because the style lives in a written spec, it can be adjusted deliberately, and every change is
applied consistently from the next run onward.

## 6. Where the news comes from

Version 1 uses only free, public, keyless sources, so there are no paid subscriptions to
maintain:

- **Google News search feeds.** The main relevance engine. The tool runs a set of standing
  searches and takes the last 24 hours of results, with the real outlet named on each item.
  The current searches cover: the Strait of Hormuz, US-Iran negotiations, Houthi and Red Sea
  shipping, Israel-Lebanon-Hezbollah, Iran's nuclear program and the IRGC, Yemen and Saudi
  Arabia, and the Iran-Oman Hormuz track.
- **Direct outlet feeds**, filtered to relevant items: Al Jazeera, Times of Israel, and Al
  Arabiya.
- **GDELT**, a global news-event database, as a backbone to catch events the searches miss.

A keyword filter (Iran, Tehran, Hormuz, Houthi, IRGC, Hezbollah, Lebanon, Israel, IDF, Yemen,
Saudi, tanker, strait, nuclear, and others) keeps the mixed-topic feeds on-beat.

All of these can be changed. Adding an outlet, adjusting a search, or broadening beyond Iran to
the wider Middle East is a quick configuration change (see [Section 16](#16-requesting-changes)).

## 7. The reviewer's role

The reviewer is the quality gate, and the role is deliberate and permanent. When the draft
arrives:

1. **Glance through it** for anything off: a miscategorized item, a headline that reads wrong,
   a cluster that should or should not be there.
2. **Check the sourcing.** Anything tagged `[single-source]` is resting on one outlet for
   something load-bearing. Confirm those before they go out, or drop them.
3. **Edit as needed, then forward** to the team distribution list.

The tool drafts; the reviewer decides. This is what keeps a human on the two-source check and
means the tool never needs access to the team distribution list itself.

## 8. The searchable archive and what it unlocks

Every article the tool collects is saved to a running archive (a small database that lives in
the repository). Over time this becomes something an email thread never could: a queryable
record of the whole beat. It lets us answer questions like how tanker incidents, Strait of
Hormuz mentions, or casualty tallies trend week over week. This archive is what will power the
planned weekly rollups and trend lines. It grows automatically; no one has to maintain it.

## 9. What it does not do yet, and the roadmap

Being honest about the current limits:

- **It does not send to the team by itself.** Only the reviewer does that. This is by design,
  not a limitation to be removed.
- **No X or social feeds yet.** Direct posts from CENTCOM, UKMTO, the IDF, and named
  spokesmen are not pulled in this version, because that needs the paid X API or a manual
  watchlist. Google News surfaces much of it secondhand. Direct social is a planned addition.
- **Some feeds are occasionally unavailable.** A source that blocks automated requests or rate
  limits is skipped for that run; the draft is built from whatever came through. The tool logs
  what it skipped.
- **Delivery is a simple self-email for now.** A cleaner future version can create a real
  Outlook draft directly in the mailbox via Microsoft's email API, instead of sending an email
  to yourself.

Roadmap, in rough order: direct social/watchlist sources, the Microsoft Outlook-draft
delivery, and automated weekly rollups built on the archive.

## 10. Who does what

- **The reviewer** receives the draft each morning, checks it, and forwards it to the team.
  Requires no technical skill.
- **The administrator** does the one-time setup in [Section 11](#11-administrator-setup-one-time)
  and handles configuration changes. This is the only role that touches GitHub settings.
- **The team** receives the finished brief from the reviewer, exactly as before.

## 11. Administrator setup (one time)

*This section is for the person who manages the GitHub repository. Everyone else can skip it.*

The tool runs on GitHub Actions, so there is no server to maintain. Setup is adding a handful
of saved values.

**Step 1 — Add repository secrets.** In the repository, go to Settings, then Secrets and
variables, then Actions, then the Secrets tab, and add:

| Secret | Required? | What it is |
| --- | --- | --- |
| `ANTHROPIC_API_KEY` | Required | The Claude API key that powers the drafting step. Without it the run cannot draft. |
| `REVIEWER_EMAIL` | For email delivery | Where the morning draft is sent. |
| `SMTP_HOST` | For email delivery | The outgoing mail server. |
| `SMTP_PORT` | Optional | The mail server port. Leave unset to use the standard default (587). |
| `SMTP_USER` | For email delivery | The email address the draft is sent from, and the login name. |
| `SMTP_PASS` | For email delivery | The password for that account, usually an app password. |

**Step 2 — Optional variable.** In the same place, on the Variables tab, you may set
`IRAN_BRIEF_MODEL` to choose which Claude model to use. Leave it unset for the sensible
default. (Note this is a Variable, not a Secret; they are separate tabs.)

**Step 3 — That is it.** The weekday-morning schedule is already built into the tool.

### Understanding the SMTP settings

The four `SMTP_*` values plus `REVIEWER_EMAIL` describe the mailbox the draft is sent *from*
and who it goes *to*. "SMTP" is just the standard protocol email programs use to send mail;
the tool logs into an account and uses it to send the morning draft.

| Setting | Meaning | Typical value |
| --- | --- | --- |
| `SMTP_HOST` | Address of the outgoing mail server | `smtp.office365.com` (Microsoft 365) or `smtp.gmail.com` (Google) |
| `SMTP_PORT` | Network port for that server (optional; defaults to 587) | `587` |
| `SMTP_USER` | The full email address you send from, also the login username | `iran-brief@csis.org` |
| `SMTP_PASS` | The password for that account, usually an app password | a provider-generated app password |
| `REVIEWER_EMAIL` | Where the draft is delivered (the "To" address) | the reviewer's inbox |

Practical notes:

- Use a **dedicated or shared mailbox** if you can, not a personal account. It keeps the
  "From" line clean and avoids putting a personal password into repository settings.
- Most providers require an **app password** here rather than the everyday password,
  especially when the account uses multi-factor authentication. App passwords are limited to
  sending mail and can be revoked anytime without changing the real password.
- **Microsoft 365** (`smtp.office365.com`, port 587): IT may need to enable "SMTP AUTH" for
  that specific mailbox, since Microsoft turns it off by default.
- **Google Workspace or Gmail** (`smtp.gmail.com`, port 587): create an app password at
  <https://myaccount.google.com/apppasswords>; the regular password will be rejected.
- **Prefer not to set up email yet?** Leave all four `SMTP_*` values and `REVIEWER_EMAIL`
  unset. The tool still builds and archives the brief and keeps a downloadable copy on each
  run; it simply does not email it, and someone opens that copy and sends it manually.

## 12. Running and testing it

**The automatic schedule** runs every weekday morning on its own once the setup above is done.

**To run it on demand** (for a test, or to regenerate a brief):

1. Open the repository's **Actions** tab.
2. Choose the **Iran War Update** workflow on the left.
3. Click **Run workflow**, leave the branch as `main`, and confirm.

Within a couple of minutes the run finishes. If email is configured, the draft arrives at
`REVIEWER_EMAIL`. Either way, the finished brief is saved on the run itself: open the completed
run and download it under **Artifacts**. That artifact copy is the reliable way to retrieve any
day's brief even if email was off.

## 13. Troubleshooting and FAQ

**The morning draft did not arrive.** First check the Actions tab: did the run succeed? If the
run is green but no email came, the issue is almost always the mail settings, usually an app
password that is needed but not set, or "SMTP AUTH" disabled on a Microsoft 365 mailbox. The
brief is still available as an artifact on the run in the meantime.

**A run failed outright (red X).** Open the run and read the failed step. The most common cause
is a missing or invalid `ANTHROPIC_API_KEY`. The administrator can re-check the secret and
re-run.

**A source is missing from the brief.** Some feeds occasionally block automated requests or
rate-limit. The tool skips them for that run and notes it. This is expected and usually
self-corrects the next day.

**Can we run it more than once a day?** Yes, anytime, using the "Run workflow" button. The
schedule is separate and keeps running regardless.

**Can we change the send time, the sources, or the number of items?** Yes; all are quick
configuration changes. See [Section 16](#16-requesting-changes).

**Can we get a brief for the wider Middle East, not just Iran?** Yes; the sources and searches
are configurable and can be broadened. That is a scoped change to request.

## 14. Cost, privacy, and data handling

- **Cost.** The only ongoing cost is the Claude API usage for the daily drafting step, which
  is small (one model call per run over a capped set of headlines). The news sources are free.
  GitHub Actions runs the schedule.
- **Privacy and data.** The tool only reads public news articles. It does not collect personal
  data, and it does not have or need access to the team distribution list. The archive it keeps
  is a record of public news items (headline, source, link, date).
- **Credentials.** The API key and mail password live only in GitHub's encrypted secrets, are
  never printed in logs, and are not stored in the code.

## 15. Where to find things

- **This explainer:** `SETUP.md` in the repository (the file you are reading).
- **A finished brief for any run:** the Actions tab, open the run, then Artifacts.
- **The exact house-style rules:** `Iran War Update — Formatter Prompt.md`.
- **The project overview and layout:** the top-level `README.md`.
- **The deeper technical detail:** `pipeline/README.md`.

## 16. Requesting changes

Want different sources, a broader Middle East scope, more or fewer items, a different send
time, a second reviewer, or the finished brief exported as a document? All of these are
straightforward configuration changes. Pass the request to whoever manages the repository, and
it can be adjusted from the next run onward.
