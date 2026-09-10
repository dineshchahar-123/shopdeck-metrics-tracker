# Shopdeck Metrics Tracker — accumulated learnings

Everything established while taking this project over, from the handover through to
2026-09-03. Written to be read once end-to-end, then used as a lookup.

Ordering is by usefulness, not chronology: what is true about the system first, then the
bugs and why they happened, then the operational rules, then what is still open.

- **Live:** https://hits-tracker.xyz
- **Repo:** `pawankumar-pkaytsk/shopdeck-metrics-tracker`, branch `main`
- **Local:** `~/shopdeck-metrics-site` (this path matters — see §2)
- **Authoritative reference:** the six skills in `.claude/skills/`. This file records what
  was *learned or corrected* on top of them, including several places where the skills and
  the code disagreed and the code was wrong.

---

## 1. What the system is

A static React-in-HTML analytics dashboard for the HITS / 1k-5k growth team. No backend.

```
Metabase cards ─┐
Google Sheets  ─┼─(pipelines/*.py, nightly)──> *.json committed to the repo
BigQuery (SQL) ─┘                                        │
index.html  (ONE JSON-encoded HTML+JSX string)           │
      │  build.mjs compiles the JSX ──> public/main.js + copies *.json into public/
      ▼
Vercel (buildCommand: node build.mjs) ──> hits-tracker.xyz
```

Every number on screen was computed by a pipeline hours earlier. 29 pipelines, 34 JSON
outputs, 5 GitHub Actions workflows. The browser only reshapes (bucketing days into weeks,
splitting a list into tranches) — all real computation belongs in the pipeline.

**Vercel deploys the working directory, not a git ref.** A push alone ships nothing; a
workflow's Vercel step is what deploys. That also means a stale local data file will be
deployed if you deploy from a dirty tree.

---

## 2. This machine

| Thing | State |
|---|---|
| Repo | `~/shopdeck-metrics-site` — **not** Downloads. All 29 pipelines default to `REPO_DIR=~/shopdeck-metrics-site`; running them elsewhere writes JSON to the wrong place. |
| node / npm | 24.18.1 LTS / 11.16.0 at `~/.local/node/bin` (user-space, no sudo — there is no Homebrew on this Mac) |
| gh | 2.96.0 at `~/.local/bin/gh`, authenticated as `pratyushboppana-shopdeck` |
| vercel | via `npx vercel@latest` (59.x) |
| Python | pipelines need **3.11** (CI uses 3.11; system python is 3.9). venv at `.venv` = 3.11.15 + `google-auth requests`. Ignored via `.git/info/exclude`, not `.gitignore`. |
| PATH | exported in `~/.zshrc` |

Run pipelines with `./.venv/bin/python pipelines/x.py`, not `python3`.

### Credentials

| Path | State |
|---|---|
| `~/metabase-arr-refresh/.mbcreds` | present. `METABASE_URL`, `METABASE_USER_EMAIL`, `METABASE_API_KEY` set; **`METABASE_PASSWORD` empty** |
| `~/.vc_token` | **missing** — no manual deploys possible |
| `~/Downloads/metrics-tracker-automation-*.json` (Google SA) | **missing** — the 6 Sheets-backed pipelines cannot run fully locally |

CI has its own copies as repo secrets (`METABASE_URL`, `METABASE_USER_EMAIL`,
`METABASE_PASSWORD`, `METABASE_API_KEY`, `GOOGLE_SA_KEY`, `VERCEL_TOKEN`). Every pipeline
checks the CI env var **first** and only then falls back to a local path, which is why
**CI is fully machine-independent** — the nightly never ran from anyone's laptop. The
"it must run from my machine now" concern was unfounded; the real dependency was on
*credentials and account ownership*, not hardware.

**The empty `METABASE_PASSWORD` costs real money.** The documented quota-saving trick is to
fall back to a *session token*, which returns Metabase's **cached** result and consumes no
BigQuery quota. It needs the email+password. Without them every local card read forces a
fresh scan. Filling that one field is the cheapest available fix for the quota problem.

---

## 3. The zip-transfer corruption (how the handover arrived broken)

The project was moved as a zip. That silently destroyed more than it appeared to:

- **The entire git object database** — `count-objects` reported 0 objects; only refs and the
  index survived, so `git status` failed with `fatal: bad object HEAD`.
- **100 tracked files**, including **5 of the 6 `.claude/skills/*/SKILL.md`** — so the skills
  that were supposed to guide the handover were not loadable.
- **`node_modules`** — `@babel/core` was present as a directory but missing `lib/index.js`,
  so `build.mjs` failed with `ERR_MODULE_NOT_FOUND`.

Repair: `git fetch origin main` (re-downloads objects), `git update-ref`, `git reset --hard
origin/main`, `git reflog expire --expire=now --all` to clear stale reflogs from the previous
owner's machine, then `rm -rf node_modules && npm install`.

**Rule: after any file-level move of this repo, do not trust it.** Run `git fsck`,
`git status`, and `node build.mjs` (must end `Babel dropped: true`) before believing the tree.

---

## 4. Data sources

52 Metabase cards, 8 Google Sheets, 5 directly-queried BigQuery tables, plus 23 internal
cross-reads between pipelines. Full catalogue with card names and consumers:
**https://claude.ai/code/artifact/798c60a3-df1c-4bfc-9232-c3385ed3db2a**

### Cards by database — this grouping is the operationally important one

| DB | Scope | Cards | Note |
|---|---|---|---|
| **6** | `nushop`, `csv_upload`, `fb_marketings` | **38** | Small daily quota (single-digit GB), resets 00:00 IST. **This is what runs out.** |
| **23** | Google/Facebook Seller PNL, churn cohort | 7 | 1 TB/day. Roomy — safe for heavy per-seller pulls. |
| **2** | team / meta mapping | 6 | |
| **3** | creative cost | 1 | |

**Biggest single dependencies:** card **7753** (`seller_manager_mapping`) read by 9
pipelines; card **10453** (`hits master`) by 5. `ts_data.json` is read by 5 pipelines.

### The 8 sheets

| Sheet / tab | Range | Role |
|---|---|---|
| **Daily Plan** | `A:AK` (`A:G` where only status is needed) | col E = Seller Id, **col G = Status**, col P = CRM Status. **Two header rows — data starts at index 2.** |
| **handover** | `A:J` | col C = Seller ID, **col J = Handover Status** (True/False). Historical: one row per HIT week, **latest row wins**. |
| escalation (`Raw_Suggested`) | `A:P` | seller escalations |
| spendinputs | `A2:H` | manual spend inputs |
| HITS 2 Handover | `A2:F` | HIT2 owner at conversion |
| Collated | `A2:D` | canonical 1k-5k GL list, HIT2 targets per GC |
| Validation | `J1:J200` | GM daily-output validation |
| Strikes | `A2:I` | L&T strike log |

**Trick when you lack the Google SA key:** four of these are pulled by `build.mjs` at deploy
time into gitignored JSON and are then served publicly —
`curl https://hits-tracker.xyz/daily_plan.json` (also `handover.json`, `escalation.json`,
`spendinputs.json`). That is how to inspect sheet contents with no credentials. Use a
generous `--max-time`; `escalation.json` is ~44 MB.

**Beware of number collisions when auditing sources.** `3540` (the 3K weekly spend gate) and
`11800` (the churn revenue floor) are *threshold constants* that each collide with a real but
unrelated Metabase card ID. A naive grep for 3–6 digit numbers reports them as data sources.
Resolve only identifiers actually interpolated into an `api/card/...` path.

---

## 5. Business definitions — including three the code had wrong

### The 1k-5k book (settled after two corrections from the team)

```
book = (ts_data hitsMap[good=0]  UNION  Daily Plan Status=='5K_HIT')  AND  handover col J == True
```

Each clause is load-bearing:

- **`hitsMap` alone is wrong.** `hit_master_data.team` is stale in *both* directions: it keeps
  sellers who have left the book, and drops sellers still being serviced whose `team` was
  cleared (e.g. Blashyslashy, Life Fashion: `team=NULL, hit2=NULL`, handover complete).
- **Daily Plan `Status` alone is too strict.** A seller who moves to `Churned` / `Revenue` /
  `Unassigned` stops being `5K_HIT` but is **still in the Google book** — that was exactly the
  six sellers the team asked to have restored (PURI HANDICRAFT, Aabhira, Rangeen, Tiny vibes,
  CHEF CENTRIC LLP / "Trishna Housewares", Zenius India). So the two rosters **union**; they do
  not intersect.
- **The handover flag is the entry condition.** `Handover Status = False` means the seller
  exists in `hit_master_data` with `team='HITS'` but has **not** been handed to the 1k-5k team
  yet. That was the "not hit1 or hit2" six.

A separate, well-documented symptom of the same stale column: `hitsMap` is a **HIT1** roster —
converting to HIT2 clears `team`, so most HIT2 sellers fall out of it entirely.

**These sheets are edited during the working day.** K M ENTERPRISES flipped
`Handover Status` False→True within 12 hours on 2026-08-06, which legitimately moved it into
the book after the team had listed it for removal. Never trust a cached sheet dump for a
roster decision without checking its `generatedAt`.

### HIT1 / HIT2 exclusivity — two conventions coexist on purpose

| View | Convention |
|---|---|
| Weekly Metrics, Google cohorts (card 11815 `_G15UNI`) | HIT1 and HIT2 **overlap** by design |
| Churn cohort, Google Seller Book | **mutually exclusive** — a churn cohort must not double-count, and the team reads the HIT1 toggle as "still in the 1k-5k book" |

Always check which convention a view uses. HIT1+HIT2 is the union either way, so the combined
figure agrees across views.

### Seller age: tenure vs conversion lag — do not confuse these

- **Tenure** = months from the seller's HIT month to now. Source: card 10453
  `hit_month`/`hit_year`. This is what the per-age targets use.
- **Conversion lag** = golive month − HIT month. This is what the
  *"HIT1 → Google Golive Conversion — Cohort by HIT Month"* table means by M0/M1/M2
  (`M0 = golive same month as HIT1`).

They are different quantities. The team initially pointed at the conversion-lag table as the
source of "the age"; using it would have made all six new target columns wrong.

### The per-tenure targets (Google Seller Book)

| | M0 | M1 | M2 | M3 | M4+ |
|---|---|---|---|---|---|
| Go-live % | 55 | 65 | 75 | 75 | 75 |
| Spend/Live % | 80 | 70 | 60 | 50 | 50 |
| Hits % (cumulative) | 10 | 20 | 30 | 40 | 45 |

"Hit" here = a **3K spend hit** (`last7 > 3540`), not a HIT2 conversion. Achieved metrics are
`live / total assigned` and `3K / total assigned`.

Because that table's rows are GL/GM/CL (people) and not cohort ages, each row's target is the
**mean of its own sellers' per-age targets** — blended over that row's actual age mix. Sellers
with an unknown age are excluded from the blend rather than defaulted, so they cannot drag a
target down; `dq.ageMix` / `dq.ageUnknown` expose the coverage.

The Hits vector already existed as `bev2.googleHitCohort.targetVec = {M0:10, M1:10, M2:10,
M3:10, M4:5}` — incremental values that cumulate to exactly 10/20/30/40/45.

### ARR cohort targets

The table displays a `TARGET` row **and** a `NEW TARGET` row. NEW TARGET is the live one:

| M0 | M1 | M2 | M3 | M4 | M5 | M6 |
|---|---|---|---|---|---|---|
| 1,859 | 4,035 | 4,960 | 5,824 | 6,647 | 6,970 | 7,435 (= 1.6 × M5) |

---

## 6. Every bug found and fixed

### 6.1 L&T person picker dropped a GC (`lt_refresh.py`)
Sohan Floyd Lobo (WM1706) was missing from the batch person picker while still being counted
in the batch's "3 GC(s)" label. Root cause: the HR roster (card 11431) and the assignment data
(`gc_data.byGC`) spell names differently —

```
HR "SOHAN FLOYD LOBO"        vs  assignment "SOHAN LOBO"
HR "Dhiraj Kumar Khandelwal" vs  assignment "Dhiraj Kumar Dhiraj Kumar Khandelwal"
```

The lookup was an exact lowercased-name match, so those people got `matched=False` →
`cur=None` → no `gcDetails` entry → silently absent. Added `resolve_gc()`: exact name first,
then a **first+last token fallback used only when it resolves to exactly one GC**, so it can
never mis-attribute a book. Verified: matched 42 → 44, exactly those two people, zero
regressions, zero collisions.

> **As of 2026-09-03 WM1706 reads `matched: false` again — and that is now correct.**
> `SOHAN LOBO` no longer exists in `gc_data.byGC` at all (no GC name contains "lobo"), i.e. he
> has no assigned sellers. The fallback correctly *refuses* rather than guessing. `matched:
> false` is a legitimate state, not automatically a bug.

### 6.2 Google Seller Book population (three iterations)
See §5. Final rule shipped; `dq.bookSource` records which sources actually contributed.

### 6.3 The 403 that silently degraded the book for 3 days
My own `read_sheet_sa` copy in `google_sellers_refresh.py` passed the URL straight to
`urlopen` **without the `Authorization: Bearer` header**. Sheets answered
**`403 Forbidden`**, both callers caught it and degraded quietly, and every nightly from
2026-08-07 rebuilt the book from `hitsMap(good=0)` alone. Blashyslashy dropped out and the
handover gate was not applied at all.

It never showed locally because a local sheet dump short-circuits the live read — **only CI
exercised the broken path.**

> **`dq.bookSource` is the canary.** It must read
> `hitsMap ∪ DailyPlan[5K_HIT] ∧ handoverDone`. Anything shorter means a sheet read failed and
> the roster silently narrowed.

Also added `LOCAL_MAX_AGE_H = 18`: beyond that a local dump is ignored in favour of a live
read, with the stale copy kept only as a last resort ahead of degrading to `hitsMap`.

### 6.4 Churn cohort double-counted every HIT2 seller
Section 4 read HIT1 = 278 when it should have been 234. Card 12159's HIT1 leg is

```sql
WHERE good_seller IS NULL AND (team='HITS' OR hit2=1) AND hit_year_week IS NOT NULL
```

so every HIT2 seller was emitted as HIT1 as well — at the card level `HIT1 ∩ HIT2 = 44 of 44`.
The card's REVENUE leg *does* exclude hit sellers (`NOT IN hit_sids`), which proves mutual
exclusivity was the intent and the HIT1 leg simply missed it.

Fixed pipeline-side (drop duplicate HIT1 rows), which is idempotent — a no-op once the card's
SQL is fixed at source. **The card SQL is still the root cause and is still unfixed.**

Also: 234 is correct and is *not* the current book of ~229. A churn cohort must retain sellers
who have since left — 53 of the 234 had churned. Reconciliation was 220 in both + 14 who moved
to Assigned/Unassigned/Revenue/Churned; the book = those 220 + 6 HIT2 graduates + 3 HIT before
Feb-2026.

### 6.5 "Total HIT2 = 45 but should be 49" — not a bug
Every independent count in the tracker agreed at 45–46, and on the card itself *every*
candidate definition (distinct `hit2=1`, with `hit2_month/year`, with `hit2_year_week`, with
`good_seller IS NULL`) returned 45. An overnight nightly then moved it to 49 — **August
conversions went 2 → 6**. The population had simply grown by 4.

Two genuine latent bugs were fixed anyway (both no-ops that day):
- `if hm is None or hy is None: continue` dropped any `hit2=1` seller whose month/year was not
  yet populated. Now bucketed as `Unknown` instead of vanishing.
- the value was `len(hit2_detail)`, a **per-row** count over a *historical dump*, so a seller
  with two hit2 rows counted twice. Now de-duplicated per seller, earliest month wins.

Also added a permanent `[bev] HIT2 variant counts: …` log line so the next such question
answers itself for free.

**Lesson: before hunting a definitional bug, check whether the population simply moved.**
Populations here drift within a single day.

### 6.6 `gm_daily.yml` had never once executed
Cancelled **6 days out of 6**. It was cron'd for `50 2 * * *` — 20 minutes *after* the nightly
starts — and all five workflows share `concurrency: data-write`, where GitHub keeps only **one
pending run per group** and a newer arrival cancels the older pending one. So it queued behind
a ~45-minute nightly and was superseded by the next `ts_refresh`/`gc_refresh`, forever. No data
was lost (both its pipelines also run in the nightly).

Moved to `30 4 * * *` (10:00 IST). **This half-worked — see §8.1.**

### 6.7 ARR cohort coloured against the wrong target
`ArrCohortRefTable` displayed both TARGET and NEW TARGET but coloured cells against the **old**
TARGET, so a cell could read green while sitting below the target the team works to. The NEW
TARGET vector was trapped inside the row's IIFE; hoisted it and added `tgtOf(c)`. Three cells
flipped, and M6 gained a target where it had none.

Scoped deliberately to that component: the identical colouring line also exists in
`BevCohort`, which shows **only** the old TARGET row, so its colouring must keep matching what
it displays.

### 6.8 "Acceptance" was mislabelled
It computes `google assets created / total assigned` → renamed **Asset creation %**. The
unrelated *golive funnel* stage legitimately named "Acceptance" (Acceptance → Asset Creation →
QC → Activation → Funds Addition → Golive) was left alone.

### 6.9 Six new columns added
`Go-live Target (%)`, `Go-Live achieved (%)`, `Spend/Live Target (%)`, `Hits Target (%)`,
`Target achieved (%)` — per §5. Target cells render as plain text, never drilldowns: a blended
target has no seller list behind it.

---

## 7. Operations playbook

### BigQuery quota — the thing that breaks most often
- **db 6 is the choke point** (38 of 52 cards, single-digit GB/day, resets **00:00 IST /
  18:30 UTC**). Symptom: `HTTP 400: Bad Request`.
- **A failed query still burns quota. Never retry blindly.**
- **Prefer an existing card over new SQL**; cards used by the nightly are usually cached.
- **The session-token path returns Metabase's cached result and costs no quota** — but needs
  `METABASE_USER_EMAIL`/`PASSWORD`, which are empty locally.
- **Card metadata is free.** `GET /api/card/<id>` returns name, SQL and database with no
  BigQuery cost — that is how the 52-card catalogue was built, and how to read a card's SQL
  without running it.
- **db 23 has 1 TB/day** — route heavy work there when the table exists in both.

### Green ≠ success
Every pipeline step in `refresh.yml` is `continue-on-error: true`, so a step can crash and the
run still shows green. **Always `grep -c Traceback` on the run log.** This is exactly how the
403 hid for three days.

### The git-clobber trap
All five data-writing workflows share `concurrency: data-write` and their commit step does
`git pull --rebase -X ours`, where **upstream wins** — so a run can discard its own fresh data.
When pushing locally, use a plain `git rebase origin/main`, never `-X ours`, and **re-verify
the data file after any rebase** before deploying.

### Deploying
`~/.vc_token` is missing, so manual `npx vercel --prod` is unavailable. Deploys happen via a
workflow's Vercel step. `gh workflow run ts_refresh.yml` (~3 min) is the lightest.

> **But do not use a data workflow purely to deploy a frontend change.** On 2026-07-30 three
> `ts_refresh` triggers in ~45 minutes exhausted the daily quota: first `scaling_refresh`
> started failing `HTTP 400`, then `ts_refresh` too. Nothing was corrupted — those pipelines
> crash *before* writing, so the previous files survived — but Spend/Live and Troubleshoot data
> went stale until the quota reset. **Getting `~/.vc_token` is the durable fix**: a
> frontend-only change then deploys in ~1 minute touching no pipelines and no quota.

### Editing `index.html`
The whole app is one JSON-encoded string inside
`<script type="__bundler/template">`. Decode → replace with `assert html.count(old) == 1` →
re-encode. Then `node build.mjs` (success ends `Babel dropped: true`).

Two traps hit in practice:
- **The uniqueness assert earns its keep.** `const good = CO.target[c] != null && ...` existed
  in *two* components; the assert caught it and the script aborted before writing.
- **Apostrophes break single-quoted JS strings.** A footnote containing `row's` terminated the
  string and failed the Babel parse. Reword, or escape.

Also: drilldown columns need a `render`, not just a `get`, or they render blank.

---

## 8. Open items

### 8.1 `gm_daily.yml` now fails every day (regression from my own fix)
The cron move worked — it *runs* now instead of being cancelled. But `30 4 * * *` lands
immediately after the nightly has consumed card **7682**, so step 1 (`golive_refresh`) fails
`HTTP 400` on quota, and because gm_daily's steps have **no `continue-on-error`**, steps 2–4
are **skipped** — including GM compliance (the job's whole purpose) and the deploy. Failing
5+ days straight as of 2026-09-03.

No data is lost: the nightly runs both pipelines fine (`[golive] card 7682: 26596 rows`,
0 Tracebacks) and both files are fresh.

**Recommended fix:** move it well clear of the nightly (e.g. `30 8 * * *` = 14:00 IST) **and**
make the `golive` step `continue-on-error: true` so a quota blip stops blocking GM compliance.
Or delete the workflow as redundant, since both pipelines already run nightly.

### 8.2 Card 12159's SQL is still the root cause of the churn double-count
One-line change: the HIT1 leg should exclude `hit2=1`. Patched pipeline-side only, so any
*other* consumer of that card still sees inflated HIT1. Needs a decision to edit a shared
Metabase asset.

### 8.3 `GOOGLE_HANDOVER_DONE` is 10 hardcoded seller IDs
"Google handover done" exists in **no reachable field** — not card 10453, not the handover
sheet, not the Daily Plan, and not `seller_managers.google_growth_lead` (only 6 of the 10 have
one, while 29 sellers who are *not* handed over do). Hardcoded in
`google_sellers_refresh.py`, same pattern as `bev_refresh`'s `COHORT_EXCLUDE` (26 IDs).
**It will go stale.** Ask ops for a real column.

### 8.4 Credentials still missing locally
`~/.vc_token` and the Google SA key. And `METABASE_PASSWORD` is empty, which disables the
quota-free cached read path.

### 8.5 Ownership
**Progress:** the Metabase API key **has been rotated** to a service identity
(`hits-incentive-pipeline`) — it is no longer Pawan's personal key. His old key is still valid
though and should be revoked once the new one is proven.
Still outstanding: the repo sits under the personal account `pawankumar-pkaytsk` (you have
write, **not admin**), and the cards were authored on a personal account.

### 8.6 The repo is public
Every `*.json` is committed, so seller-level ARR/spend detail is downloadable by anyone even
though the dashboard sits behind Google login. Accepted deliberately on 2026-07-30; worth
revisiting when the repo moves to an org.

### 8.7 Data-entry gaps worth chasing with ops
- `6a0da009cd8b4aff768990c0` is `5K_HIT` in the Daily Plan but has **no name and no
  hit_year_week** in card 10453, so it renders with a blank seller name.
- `68ef094e…` is "Trishna Housewares" to the team but still **CHEF CENTRIC LLP** upstream in
  card 7336.
- `dq.ageUnknown` is 1 as of 2026-09-03 — one seller with no derivable HIT month.

---

## 9. Verification discipline that actually caught things

1. **Verify data, don't trust the render.** After every change, re-read the JSON and assert the
   specific numbers. Every fix here was confirmed against source data before shipping.
2. **Check your own comparison logic before declaring a data bug.** A 5-rupee discrepancy in
   the ARR tranches looked like a bug; it was Python's banker's rounding vs JS `Math.round`.
   Re-running with `math.floor(x+0.5)` reproduced the UI exactly.
3. **Unit-test the shipped code, not a paraphrase of it.** For the `resolve_gc` fix I extracted
   the function's source verbatim out of the pipeline file and `exec`'d it against real data —
   which proved 0 regressions and 0 collisions rather than assuming.
4. **State the as-of time next to any count.** The 1k-5k book read 240 → 229 → 238 → 248 across
   a few days; HIT2 went 45 → 49 → 60. None of those were bugs.
5. **Assert invariants, not just totals.** `HIT1 ∩ HIT2 == 0`, `every row is h1 or h2`,
   `union preserved`, `no two employees resolve to the same GC`, `retained sellers keep
   byte-identical metrics`. The collision check is what made the name-fallback safe to ship.
6. **Diff everything you did not intend to change.** When splicing `churnCmp` into
   `bev_data.json` I asserted every *other* `bev2` key was byte-identical and that
   `cards.cohort` was still a dict with `tva`.

---

## 10. Mistakes I made — recorded so they are not repeated

1. **Burned the BigQuery quota by triggering three `ts_refresh` runs in 45 minutes** to deploy
   frontend-only changes. Broke `scaling`/`ts` refreshes for the rest of that day. A data
   workflow is not a deploy button.
2. **Shipped a Sheets reader with no `Authorization` header.** It degraded silently for three
   days because the local-file tier hid the broken path from local testing. When you copy a
   helper, diff it against the original line by line — and make sure the failure mode is loud.
3. **Fixed `gm_daily`'s cron without fixing its error handling**, converting "cancelled every
   day" into "fails every day" (§8.1).
4. **Chose the Daily Plan `Status` filter without asking**, which silently dropped six sellers
   the team wanted. I *did* flag them explicitly as "please sanity-check", and that flag is
   what surfaced the error — surfacing the deltas mattered more than getting it right first
   time.
5. **Committed a locally-regenerated data file once while quota was failing mid-run**, which
   would have dropped CL coverage from 274 to 0. Caught it, discarded the output, and derived
   the one new field from committed data instead. **Always check a local pipeline run's log for
   partial failures before committing its output.**

---

## 11. State as of 2026-09-03

All fixes verified present and working after ~3 weeks (175 upstream commits, **zero** of them
code changes — all nightly data).

| | Value |
|---|---|
| Google Seller Book | 331 rows · HIT1 275 + HIT2 56 · `bookSource` = `hitsMap ∪ DailyPlan[5K_HIT] ∧ handoverDone` · `HIT1 ∩ HIT2 = 0` |
| Age coverage | M0 0 · M1 71 · M2 61 · M3 43 · M4+ 155 · unknown 1 |
| `cards.hit2.value` | 60 |
| Churn cohort | HIT1 278 · HIT2 59 · REVENUE 661 · overlap 0 |
| L&T | 45 of 100 GCs matched |
| CI | nightly clean (0 Tracebacks); `gm_daily` failing daily (§8.1) |
| Repo | `~/shopdeck-metrics-site` @ `ec79dd577`, clean tree, `.git` 2.1 GB |

### Fix commits

| Commit | Change |
|---|---|
| `ced7ac26` | `lt_refresh`: name-mismatch GC matching (`resolve_gc`) |
| `25ee4b79` | `google_sellers`: book from the Daily Plan sheet |
| `1bacdd98` | `google_sellers`: local `daily_plan.json` tier |
| `d2eb7cd6` / `b8f58af4` | churn cohort: stop double-counting HIT2 into HIT1 |
| `81fd5ee6` | `google_sellers`: handover flag gates the book |
| `5eb096a9` | `google_sellers`: restore the `Authorization` header |
| `7c669428` / `0e59e6e9` | HIT2 KPI: distinct-seller count + variant logging |
| `d3b5bec1` | `gm_daily`: move off 02:50 UTC |
| `ebf1a4ae` | ARR cohort colours against NEW TARGET; Acceptance renamed |
| `8e91d7e2` | Google Seller Book: six per-tenure target/achieved columns |
