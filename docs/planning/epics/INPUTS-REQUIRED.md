# Inputs Required From You

**Part of:** [Implementation Plan](README.md) · **Baselined:** 2026-08-09

Everything the build needs from you that cannot be derived from code or public data, ordered by when
it is needed. Nothing here blocks the start of work.

---

## The headline

**The steel thread (E0) needs almost nothing from you.** No API keys, no hosting account, no CI
configuration, no secrets. It runs entirely locally against public FPL endpoints. Two small
confirmations on day one and one contact string, and it can run to completion.

The first genuinely blocking input is your **FPL team ID**, and it cannot exist until you have
created your 2026/27 team — which is itself the output of E0.

---

## 1. Needed before work starts (E0 day 1)

| # | Input | Why | Default if you say nothing |
| --- | --- | --- | --- |
| 1.1 | **Confirm Python 3.14.7 is the target** | Verified working: `pulp`, `pandas` 3.0.5, `pyarrow`, `httpx`, `pydantic` all have cp314 wheels, and PuLP's bundled CBC solves the FPL squad MILP optimally. Note pandas 3.x is a major version with API changes from 2.x | Proceed on 3.14.7 |
| 1.2 | **Package manager: `uv` or `pip` + venv** | `uv` is markedly faster and lockfile-native but is not currently installed. `pip` with `pip-tools` works with what you already have | Install `uv` — worth the two minutes |
| 1.3 | **Contact string for the HTTP User-Agent** | NFR-10 requires honest client identification when calling FPL. Convention is a project name plus a contact URL or email | `fpl-dof/0.1 (+https://github.com/talonegg/fpl_dof2)` — uses the repo, exposes no personal address |

## 2. Needed during E0, before submission

| # | Input | Why |
| --- | --- | --- |
| 2.1 | **Your own football judgement, at [E0-S8](E0-steel-thread-gw1.md#e0-s8--human-verification-gate)** | The GW1 model is unvalidated by construction. The human review gate is a mandatory story, not a formality. Budget an hour |
| 2.2 | **Any hard player preferences** — must-owns, will-never-owns | The optimiser supports locks and bans from day one. Cheap to honour, and stops you fighting the tool |
| 2.3 | **Risk appetite for GW1** | Whether to hug the template or accept differentials. The steel thread has no risk dial yet, so this is a manual review posture rather than a setting |

## 3. Needed for E1, immediately after GW1

| # | Input | Why | How to get it |
| --- | --- | --- | --- |
| 3.1 | **Your FPL team ID (entry ID)** | Required by FR-25 to load your squad, bank, free transfers and chips. **This cannot exist until you have created and submitted your team** | Log in to fantasy.premierleague.com, open the "Points" or "My Team" tab, and read the number in the URL: `/entry/{THIS_NUMBER}/event/1` |
| 3.2 | **Confirmation of your timezone handling preference** | You are on AEST (UTC+10). See §7 — this needs a decision, not just a display setting | — |

## 4. Needed for E5 (external sources), around GW10–12

| # | Input | Why | Cost |
| --- | --- | --- | --- |
| 4.1 | **Odds provider account and API key** (OD-03) | Bookmaker odds are the strongest short-horizon team-level signal. The Odds API free tier is the current candidate | Free tier, credit-capped. **Requires you to sign up** |
| 4.2 | **Explicit sign-off on the scraping approach** for Understat and FBref | These are scraped, not licensed APIs. Personal non-commercial use, `robots.txt` respected, crawl-delayed, cached hard (NFR-10). You should be comfortable with that posture before it is built | None |

## 5. Hosting — **settled, nothing needed from you**

OD-01 and OD-02 are both closed by [DL-12](../00-decision-log.md#dl-12--public-repository): **the
repository is public, and the site is hosted on GitHub Pages.** No Cloudflare account to create, no
minutes budget to approve, no decision waiting at ~GW6.

### Why this reversed

The project briefly resolved OD-01 as *private*. Costing the workflow cadences afterwards showed that
the original estimate here — *"~6 scheduled runs/day × ~3 min ≈ 540 min/month, comfortably inside
2,000"* — counted only the fast ingest. It omitted the pipeline, deploy, backtest and CI workflows
entirely, and it missed that GitHub rounds every job up to a whole minute.

| Workflow | Runs/month | Min/run | Total |
| --- | --- | --- | --- |
| `ingest-fast` 4-hourly, hourly near deadlines | ~275 | 2–3 | 550–825 |
| `pipeline` after each ingest + nightly + T−3h + T−45m | ~290 | 3–6 | 870–1,740 |
| `deploy` on publish | ~290 | 1–2 | 290–580 |
| `ingest-slow`, `backtest`, `ci` | ~50 | 2–5 | 100–250 |
| | | **Total** | **1,810–3,395** |

Against a hard 2,000-minute cap, with no headroom for deadline-day reruns — which are exactly the
runs that must never be rationed.

The privacy was also mostly illusory. The published artefacts — your squad, your transfer plan, your
differentials — are served from a public CDN regardless (DL-03). A private repository protected the
code, not the decisions, while costing the compute budget the decisions depend on.

### What this asks of you instead

| # | Now required | Why |
| --- | --- | --- |
| 5.1 | **Nothing to set up** | Pages is free on a public repo; it enables in repository settings |
| 5.2 | **Awareness that every push is world-readable** | NFR-13 stops being precautionary. There is no window in which a leaked key is only "internally" exposed. The `ODDS_API_KEY` (E5) goes in Actions secrets and nowhere else; the secret-scan hook in `.claude/hooks/` is now the primary guard rather than a backstop |
| 5.3 | **A quick look at the repo before it goes public** | Nothing personal beyond a public FPL team ID should be committed — which NFR-11 already required, but it is worth one deliberate check rather than an assumption |

Two cadence rules survive from the recount and are now in
[Architecture §9](../03-solution-architecture.md#two-cadence-rules-that-are-easy-to-get-wrong), because
they were always the right design: `element-summary` never runs on the fast path, and the pipeline
does not re-solve after every fast ingest. An unbounded minutes budget is not a licence for a
wasteful pipeline, and slowness on the deadline path costs more than money.

## 6. Preferences worth settling before E4

| # | Input | Why |
| --- | --- | --- |
| 6.1 | **Target overall rank** (OD-05) | Drives the default risk-dial position. "Top 100k" and "top 1k" imply very different differential appetites |
| 6.2 | **Mini-league ID**, if you want rival analysis | Optional (FR-32). See §6a — the setting now exists and is wired end to end |
| 6.3 | **Chip philosophy** | Whether you want the tool to plan chips aggressively around doubles, or to hold them as insurance |

### 6a. Mini-league ID — optional, wired, and unset

**Nothing is blocked by this and nothing needs to happen now.** [E6-S10](E6-web-application.md#e6-s10)
built the mini-league view against the case where this is *not* set, which is the state the
repository is in and the state the tests run against.

| | |
| --- | --- |
| **Setting** | `entry.league_id` in `config/local.yaml`, or the `FPL_DOF_LEAGUE_ID` environment variable |
| **Where to find it** | Open the league on the FPL site; it is the number in `/leagues/{THIS_NUMBER}/standings/c` |
| **Secret?** | No. A classic league ID is public, as is everything the standings return (NFR-11) |
| **Companion setting** | `entry.league_rival_limit`, default 20 — how many entries from the top of the table to fetch squads for. Each costs one request, so this is the knob that decides what rival analysis costs. `0` publishes the table alone |
| **Also needs** | `entry.team_id` (3.1), for the overlap columns. The comparison is anchored on the squad you actually fielded, so without your own entry there is a table and no comparison — and the page says so rather than showing empty columns |

**With it unset:** no league is fetched, no `league.json` is published, and `/league` renders a
first-class "no mini-league configured" page explaining what setting it would unlock. **With it set:**
the table appears on the next `fpl-dof run`, and the overlap, differential and captain-divergence
columns fill in from the first gameweek that has been scored — rivals' squads cannot be read before
one has (DL-20).

---

## 7. A finding that needs your decision: timezone

**You are on AEST (UTC+10). Every FPL deadline is expressed in UK time.** In practice:

| Gameweek type | UK deadline | Your local time |
| --- | --- | --- |
| Friday-night opener (incl. **GW1**) | Fri 18:30 BST | **Sat ~03:30 AEST** |
| Standard Saturday | Sat 11:00 BST | Sat ~20:00 AEST |
| Midweek | Tue/Wed 18:30 | Wed/Thu ~03:30 AEST |

Two consequences:

1. **You will be asleep for a large fraction of deadlines.** This makes E7 automation less of a
   convenience and more of a requirement, and it moves E7 earlier in the ranking than the original
   plan assumed. It also means the practical working rule is *decide the evening before, local time*.
2. **The offsets shift mid-season.** The UK leaves BST in late October (to UTC+0) while Australia
   enters AEDT (to UTC+11) in early October. The gap moves from +9 to +11 within a few weeks. Any
   code that reasons in local time will break during that window.

**Recommended handling, needs your confirmation:**

- Store and compute in **UTC everywhere**; render in local time only at the UI edge.
- Treat "deadline minus N hours" scheduling as UTC arithmetic, never local.
- Surface both UK and local deadline times in the dashboard countdown, because FPL communities all
  talk in UK time and you will need to translate constantly.
- Add a "decide by" time that is deliberately earlier than the deadline in your local evening.

This warrants a decision-log entry; it changes FR-26 and the E7 scheduling design.

---

## 8. Environment variables

Complete set across all epics. **None are needed for E0** beyond the optional ones.

| Variable | Purpose | Needed by | Secret | Example |
| --- | --- | --- | --- | --- |
| `FPL_DOF_ENV` | Execution context: `local` or `ci` | E0 (optional) | No | `local` |
| `FPL_DOF_DATA_DIR` | Override the data root | E0 (optional) | No | `C:\JHH\data\fpl_dof` |
| `FPL_DOF_LOG_LEVEL` | Logging verbosity | E0 (optional) | No | `INFO` |
| `FPL_DOF_USER_AGENT_CONTACT` | Honest client identification (NFR-10) | E0 | No | `https://github.com/talonegg/fpl_dof2` |
| `FPL_DOF_TIMEZONE` | Local rendering zone | E1 | No | `Australia/Sydney` |
| `FPL_DOF_TEAM_ID` | Your FPL entry ID | **E1** | No — public | `1234567` |
| `FPL_DOF_LEAGUE_ID` | Mini-league for rival analysis (§6a). Optional — unset is the normal state | E6 | No | `987654` |
| `ODDS_API_KEY` | Bookmaker odds provider | E5 | **Yes** | — |
| `FPL_DOF_ODDS_CREDIT_BUDGET` | Monthly request cap, enforced in the adapter | E5 | No | `450` |

**Handling:** non-secrets go in a committed `.env.example` and a gitignored `.env`. The one secret
(`ODDS_API_KEY`) goes in `.env` locally and GitHub Actions secrets in CI — never in a settings file,
never in the client bundle (NFR-13). The secret-scan hook in `.claude/hooks/` already guards commits.

---

## 9. Summary — what to action, and when

| When | Action |
| --- | --- |
| **Now** | Confirm items 1.1–1.3. Three quick answers, then work can start |
| **Before 21 Aug** | Reserve an hour for the E0-S8 review gate |
| **Right after GW1** | Send your FPL team ID (3.1) |
| **By ~GW6** | Decide hosting (5.1) |
| **By ~GW10** | Sign up for the odds API (4.1) if you want that signal |
| **Whenever** | Confirm the timezone handling in §7 — it is the one finding that changes an existing requirement |
