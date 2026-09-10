# Shopdeck Metrics Tracker — handover to the next owner

Written 2026-09-10 by the outgoing owner (Pratyush Boppana) for whoever takes this on next.

**Read `LEARNINGS.md` in this repo alongside this file.** This document is the *transfer*:
who to ask for what, how to stand it up, and what is broken on day one. `LEARNINGS.md` is the
*substance*: every business definition, every bug and its root cause, and the operational rules.

- **Live:** https://hits-tracker.xyz
- **Repo:** `pawankumar-pkaytsk/shopdeck-metrics-tracker`, branch `main`
- **Hosting:** Vercel project `shopdeck-dashboard` (org `team_Nv7Bqm9rCMXGjFA018pplRCW`)
- **Data-source catalogue:** https://claude.ai/code/artifact/798c60a3-df1c-4bfc-9232-c3385ed3db2a

---

## 0. Do not move this repo as a zip. Clone it.

The previous handover was delivered as a zip file. That silently destroyed:

- the **entire git object database** (0 objects survived — `git status` failed outright)
- **100 tracked files**, including 5 of the 6 `.claude/skills/*/SKILL.md` files, so the skills
  meant to guide the handover were not loadable
- **`node_modules`** (`@babel/core` present but missing `lib/index.js`, so the build failed)

It cost most of a day to diagnose and repair. Just run:

```bash
git clone https://github.com/pawankumar-pkaytsk/shopdeck-metrics-tracker.git
```

If you ever do receive this repo as an archive, treat it as untrusted: run `git fsck`,
`git status`, and `node build.mjs` (must end `Babel dropped: true`) before believing it.

---

## 1. Access to request — the critical path

**Nothing here can be granted by the outgoing owner.** Pratyush has `push` but **not `admin`**,
and the repo lives on a personal account, so only `pawankumar-pkaytsk` can change access.

| # | What | Ask | Why it matters |
|---|---|---|---|
| 1 | **GitHub write** on the repo | **Pawan** (`pawankumar-pkaytsk`) — only admin | Without it you cannot commit, deploy, or trigger any workflow. Everything else is blocked behind this. |
| 2 | **Vercel** membership of the org owning `shopdeck-dashboard` | Vercel org admin | Only needed for manual deploys and the domain. CI deploys without it. |
| 3 | **Vercel deploy token** → `~/.vc_token` | Vercel org admin | See §4 — this is the single highest-value thing to get. |
| 4 | **Metabase API key** | Metabase admin | Already a **service identity** (`hits-incentive-pipeline`), not a personal key — so this is transferable cleanly. Confirm it still has the large BigQuery quota. |
| 5 | **Metabase email + password** for the same account | Metabase admin | Not optional — see §4. |
| 6 | **Google service-account key** JSON | whoever owns `metrics-tracker-automation` | Needed by 6 Sheets-backed pipelines. |
| 7 | **Sheets shared** with `tracker-sheets-reader@metrics-tracker-automation.iam.gserviceaccount.com` | sheet owners | Confirm all 8 sheets are shared, not just some. |

Existing collaborators with `push` today: `pawankumar-pkaytsk` (admin/owner),
`pratyushboppana-shopdeck`, `Rachna2108`, `roopeshb-blip`.

### Copy-paste request for Pawan

> Hi Pawan — I'm taking over the Shopdeck Metrics Tracker from Pratyush. Could you please:
> 1. add **`<my-github-handle>`** as a collaborator with **write** access on
>    `pawankumar-pkaytsk/shopdeck-metrics-tracker`;
> 2. ideally give me **admin**, or transfer the repo to an org — it currently sits on your
>    personal account, so you are a single point of failure for every access change; and
> 3. remove **`pratyushboppana-shopdeck`** once I've confirmed I'm set up.
>
> Also: the repo is **public** and every `*.json` is committed, so seller-level ARR and spend
> detail is downloadable by anyone. Worth making private when it moves to an org.

---

## 2. Day-one setup

```bash
git clone https://github.com/pawankumar-pkaytsk/shopdeck-metrics-tracker.git ~/shopdeck-metrics-site
cd ~/shopdeck-metrics-site
npm install
node build.mjs          # must end: "Babel dropped: true"
```

**The path matters.** All 29 pipelines default to `REPO_DIR=~/shopdeck-metrics-site`. Clone it
elsewhere and they write their JSON to the wrong place.

**Python must be 3.11** (CI uses 3.11; macOS system python is 3.9):

```bash
uv venv --python 3.11 .venv
VIRTUAL_ENV=$PWD/.venv uv pip install google-auth requests
echo '.venv/' >> .git/info/exclude      # note: .git/info/exclude, not .gitignore
```

Run pipelines as `./.venv/bin/python pipelines/<name>.py`, never `python3`.

Three secrets live **outside** the repo and must be recreated by hand:

| Path | Contents |
|---|---|
| `~/metabase-arr-refresh/.mbcreds` | `{"METABASE_URL","METABASE_USER_EMAIL","METABASE_PASSWORD","METABASE_API_KEY"}` |
| `~/Downloads/metrics-tracker-automation-*.json` | Google service-account key |
| `~/.vc_token` | Vercel deploy token |

CI has its own copies as repo secrets (`METABASE_URL`, `METABASE_USER_EMAIL`,
`METABASE_PASSWORD`, `METABASE_API_KEY`, `GOOGLE_SA_KEY`, `VERCEL_TOKEN`). Every pipeline reads
the CI env var **first**, which is why **CI is fully machine-independent** — the nightly has
never run from anyone's laptop. Your local setup is only for testing pipeline changes.

### Prove it works

```bash
node build.mjs                                   # "Babel dropped: true"
./.venv/bin/python pipelines/hit2_refresh.py      # small, fast, real Metabase read
gh workflow run ts_refresh.yml -R pawankumar-pkaytsk/shopdeck-metrics-tracker
gh run view <id> --log | grep -c Traceback        # MUST be 0 — see §5
```

---

## 3. Broken on day one — inherited defects

### 3.1 `gm_daily.yml` fails every single day
Has failed **every day since 2026-08-11** (roughly a month). It runs at `30 4 * * *`, which
lands right after the nightly has consumed card **7682**, so step 1 (`golive_refresh`) hits
`HTTP 400` on BigQuery quota. Because that workflow's steps have **no `continue-on-error`**,
steps 2–4 are **skipped** — including GM compliance, which is the job's entire purpose, and the
deploy.

**No data is lost** — both its pipelines also run in the nightly and both files stay fresh. It
is pure daily red noise plus a missing mid-morning refresh.

**Fix:** move it well clear of the nightly (e.g. `30 8 * * *` = 14:00 IST) **and** set
`continue-on-error: true` on the `golive` step so a quota blip stops blocking GM compliance.
Or delete the workflow as redundant.

*History worth knowing:* before 2026-08-11 this job was **cancelled** 6 days out of 6 and had
literally never executed — it was cron'd 20 minutes *after* the nightly starts, and all five
workflows share `concurrency: data-write` where GitHub keeps only one *pending* run per group.
Moving the cron made it run; it now fails instead. Both halves need fixing.

### 3.2 Card 12159's SQL still double-counts HIT2 into HIT1
Its HIT1 leg is `WHERE good_seller IS NULL AND (team='HITS' OR hit2=1) …`, so every HIT2 seller
is emitted as HIT1 too. The card's own REVENUE leg *does* exclude hit sellers, which proves
mutual exclusivity was the intent. Patched **pipeline-side only** (idempotent), so the
dashboard is correct but **any other consumer of that card still sees inflated HIT1**. The
durable fix is one line on the card.

### 3.3 `GOOGLE_HANDOVER_DONE` is 10 hardcoded seller IDs
"Google handover done" exists in **no reachable field** — not card 10453, not the handover
sheet, not the Daily Plan, not `seller_managers.google_growth_lead`. Hardcoded in
`google_sellers_refresh.py`. **It will go stale.** Ask ops for a real column.
(`bev_refresh` has a similar `COHORT_EXCLUDE` list of 26 IDs.)

### 3.4 Data-entry gaps to chase with ops
- `6a0da009cd8b4aff768990c0` is `5K_HIT` in the Daily Plan but has no name and no
  `hit_year_week` in card 10453 → renders with a blank seller name.
- `68ef094e…` is "Trishna Housewares" to the team but still `CHEF CENTRIC LLP` upstream.

### 3.5 The repo is public
Every `*.json` is committed, so seller-level ARR/spend is downloadable by anyone even though the
dashboard sits behind Google login. Accepted deliberately; revisit on the move to an org.

---

## 4. Get `~/.vc_token` and the Metabase password on day one

These two are worth more than they look.

**`~/.vc_token`** — without it you cannot deploy manually, so the only way to ship a
frontend-only change is to trigger a *data* workflow, which re-runs pipelines and burns
BigQuery quota. That mistake broke `scaling`/`ts` refreshes for a day: three `ts_refresh`
triggers in ~45 minutes exhausted db 6. With the token, a frontend change deploys in about a
minute and touches no quota:

```bash
node build.mjs && npx --yes vercel@latest --prod --yes --token "$(cat ~/.vc_token)"
```
(Give it a ≥7-minute timeout — it takes longer than 2 minutes.)

**`METABASE_PASSWORD`** — the documented quota-saving path is a *session-token* fallback, which
returns Metabase's **cached** result and costs **no quota**. It needs the email **and**
password. The outgoing `.mbcreds` has the password field empty, so every local card read forces
a fresh BigQuery scan. Filling that one field is the cheapest fix for the recurring quota
problem.

---

## 5. The three rules that will save you the most time

1. **Green ≠ success.** Every step in `refresh.yml` is `continue-on-error: true`, so a pipeline
   can crash and the run still shows a green check. **Always `grep -c Traceback` on the log.**
   A missing `Authorization` header once degraded the Google Seller Book for three days behind
   green checks; the only visible symptom was a `dq` field.

2. **Verify data, don't trust the render.** After any change, re-read the JSON and assert the
   specific numbers. Populations here drift *within a single day* — the 1k-5k book read
   240 → 229 → 238 → 248 across a few days and HIT2 went 45 → 49 → 60. None of those were bugs.
   Always state the as-of time next to a count.

3. **`index.html` is one JSON-encoded string.** Decode → replace with
   `assert html.count(old) == 1` → re-encode → `node build.mjs`. The uniqueness assert is not
   ceremony: it has caught a snippet that existed in two different components. Watch for
   apostrophes — a footnote containing `row's` terminated a single-quoted JS string and failed
   the Babel parse.

`LEARNINGS.md` §7 has the full operational playbook (quota, the git-clobber trap, deploy).

---

## 6. Canary fields — check these first when something looks wrong

| Field | Must read | If not |
|---|---|---|
| `google_sellers_data.json` → `dq.bookSource` | `hitsMap ∪ DailyPlan[5K_HIT] ∧ handoverDone` | a sheet read failed and the roster silently narrowed |
| `bev_data.json` → `cards.cohort` | a **dict** containing `tva` | a variable-shadowing bug once wrote it as the string `'M0'` and blanked two whole views for two days |
| `bev2.churnCmp` → HIT1 ∩ HIT2 | **0** | the card-12159 double-count is back |
| `dq.ageUnknown` | small | the per-tenure targets are being blended over fewer sellers |

---

## 7. What the outgoing owner is handing over

- `LEARNINGS.md` — exhaustive: system, machine setup, all 52 data sources, business
  definitions (including three the code had wrong), all nine bugs with root causes,
  operational playbook, open items.
- `.claude/skills/` (6 skills) — load automatically in Claude Code once cloned.
- The data-source catalogue artifact (link at top).
- This file.

**Not** handed over, because it cannot be: any GitHub, Vercel, Metabase or Google access. All of
that has to be granted by the owners listed in §1.

---

## 8. Checklist

**New owner**
- [ ] GitHub write access confirmed (`gh api repos/<repo> --jq .permissions`)
- [ ] Cloned to `~/shopdeck-metrics-site` (**not** a zip)
- [ ] `node build.mjs` ends `Babel dropped: true`
- [ ] `.venv` on Python 3.11 with `google-auth requests`
- [ ] `.mbcreds` created — including **password**, not just the API key
- [ ] `~/.vc_token` created; a manual `vercel --prod` succeeds
- [ ] Google SA key in place; a Sheets-backed pipeline runs without `403`
- [ ] `gh workflow run refresh.yml` completes **and** `grep -c Traceback` is 0
- [ ] Read `LEARNINGS.md` end to end

**Outgoing owner**
- [ ] Ask Pawan to add the new owner (§1)
- [ ] Confirm the new owner has run a full refresh successfully
- [ ] Hand over `.mbcreds`, the SA key and the Vercel token by a secure channel — never in chat,
      never committed
- [ ] Ask Pawan to remove `pratyushboppana-shopdeck`
- [ ] Ask Metabase admin to revoke Pawan's old personal key
      (`METABASE_API_KEY_OLD_PAWAN` in `.mbcreds`) — still valid and superuser

**Still on Pawan / org admins**
- [ ] Move the repo off the personal account to an org (removes the single point of failure)
- [ ] Reparent the Metabase cards from a personal account to a service/team account
- [ ] Decide on repo visibility (§3.5)
