# Reliable scheduling for the Iran War Update

## Why this exists

The brief is triggered by GitHub Actions `schedule:` crons in
`.github/workflows/iran-brief.yml`. GitHub is explicit that scheduled workflows are
**best-effort**: under load a run can be delayed by an hour or more, fired late, or **dropped
entirely**. We have seen all three:

- **2026-08-27** — the morning slot was dropped, then fired ~10 hours late in the evening.
- **2026-08-28** — *every* morning slot was dropped; no run fired at all.

Two mitigations already live in the repo:

1. **Once-per-day delivery guard** (`pipeline/deliver.py`) — records the delivered date in the
   archive DB and skips any later send for a date already delivered, so a late or duplicate
   slot never re-emails the team.
2. **Staggered backup crons** (12:10, 13:10, 14:10, 15:10 UTC) — several attempts across the
   morning, deduped by the guard.

Those reduce the damage but **cannot force GitHub to fire a cron it decided to skip**. The
only way to make the morning send reliable is to trigger it from an **external scheduler** that
calls GitHub's `workflow_dispatch` API on time. That is what this document sets up. The GitHub
crons stay as a free redundant fallback; the guard makes the extra triggers harmless.

## What you are setting up

An external cron service fires once each weekday morning and sends an authenticated
`POST` to the workflow's dispatch endpoint. That starts the exact same pipeline a manual
"Run workflow" click starts — sending to the full `DIGEST_TO` list and marking the day
delivered.

- **Endpoint**
  ```
  POST https://api.github.com/repos/andysaulim/Middle-East-Digest/actions/workflows/iran-brief.yml/dispatches
  ```
- **Headers**
  ```
  Authorization: Bearer <TOKEN>
  Accept: application/vnd.github+json
  X-GitHub-Api-Version: 2022-11-28
  Content-Type: application/json
  ```
- **Body** (a normal, full-list run; leave `digest_to` unset so the guard marks the day)
  ```json
  {"ref": "main"}
  ```
  A successful dispatch returns **HTTP 204 No Content** with an empty body.

## Step 1 — Create a scoped GitHub token

Use a **fine-grained personal access token** limited to this one repository:

1. GitHub → **Settings** → **Developer settings** → **Personal access tokens** →
   **Fine-grained tokens** → **Generate new token**.
2. **Resource owner:** `andysaulim`. **Repository access:** *Only select repositories* →
   `middle-east-digest`.
3. **Permissions** → **Repository permissions** → **Actions: Read and write**. (That single
   permission is all `workflow_dispatch` needs. Leave everything else at *No access*.)
4. Set an expiry you're comfortable rotating (e.g. 90 days) and generate. Copy the token now;
   GitHub shows it once.

Treat the token like a password. It goes only into the scheduler service below — never commit
it to the repo.

## Step 2 — Point a cron service at the endpoint

Any scheduler that can send a POST with custom headers works. A free, no-infra option is
**cron-job.org**; a Cloudflare Worker on a cron trigger is a good code-based alternative.

### Option A — cron-job.org (no code)

1. Create an account, then **Create cronjob**.
2. **URL:** the dispatch endpoint above.
3. **Schedule:** every weekday at **08:40** in timezone **America/New_York**. An external
   trigger fires on time (unlike GitHub's crons, which we started ~50 min early to absorb their
   delay), and the pipeline takes ~15 min, so 08:40 lands the brief around 9:00 AM ET. Pick an
   earlier time if you'd rather it arrive sooner. Picking the ET timezone (not UTC) means the
   service handles the EDT/EST switch for you, so the brief keeps landing at the same local
   time year-round — something the fixed-UTC GitHub crons cannot do.
4. **Request method:** `POST`.
5. **Headers:** add the four headers listed above (put the token in `Authorization`).
6. **Body:** `{"ref": "main"}`.
7. Enable **"Save responses"** / notifications so you're alerted if a fire ever returns
   something other than 204.

### Option B — Cloudflare Worker (code)

A Worker with a `crons` trigger and the token stored as a secret:

```js
// wrangler.toml:  [triggers]  crons = ["10 12 * * 1-5"]   # 12:10 UTC; adjust for EST months
export default {
  async scheduled(_event, env) {
    await fetch(
      "https://api.github.com/repos/andysaulim/Middle-East-Digest/actions/workflows/iran-brief.yml/dispatches",
      {
        method: "POST",
        headers: {
          "Authorization": `Bearer ${env.GH_DISPATCH_TOKEN}`,
          "Accept": "application/vnd.github+json",
          "X-GitHub-Api-Version": "2022-11-28",
          "Content-Type": "application/json",
          "User-Agent": "iran-brief-scheduler",
        },
        body: JSON.stringify({ ref: "main" }),
      },
    );
  },
};
```

Store the token with `wrangler secret put GH_DISPATCH_TOKEN`. Cloudflare cron triggers are
fixed-UTC like GitHub's, so if you use a Worker you still adjust the hour by one at the DST
switch (or schedule both 12:10 and 13:10 UTC and let the guard dedupe). cron-job.org's
timezone support avoids that entirely, which is why it's the simpler default.

## Step 3 — Verify

1. In the scheduler, use its **"Run now" / "Test"** action.
2. The endpoint should return **204**. Within a few seconds a new **Iran War Update** run
   appears under the repo's **Actions** tab with event **workflow_dispatch**.
3. Let it finish (~10–15 min) and confirm the brief arrives.

Once verified, the external trigger is your primary on-time send and the GitHub crons are the
backup. Nothing double-sends: whichever fires first marks the day delivered and the guard
suppresses the rest.

## Rotating the token

When the token nears expiry, generate a new one (Step 1) and update it in the scheduler. No
repo change is needed — the token lives only in the scheduler service.
