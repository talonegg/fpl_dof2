# Architecture Review: Data Sources, Fetch, Bronze & Silver Layers

**Document Reference**: `docs/architecture/archive/20261017/data-pipeline-design.md`  
**Date**: 2026-10-17  
**Scope**: FPL DOF pipeline — Data Sources, Ingestion Transport, Bronze Snapshotting, Conformance, and Silver Parquet Tier.

---

## 1. Architectural Philosophy & Core Invariants

The ingestion and conformed data architecture is governed by binding design principles (see `docs/DESIGN-PRINCIPLES.md`) that enforce reproducibility, cost discipline, and defensive boundary management:

1. **Source Encapsulation (Invariant 1 & DP-01)**:
   - Downstream modules (`transform`, `quality`, `forecast`, `optimise`) **never** import, name, or branch on specific data sources.
   - Sources register via `@register` in [`pipeline/src/fpl_dof/sources/registry.py`](file:///c:/JHH/source/fpl_dof2/pipeline/src/fpl_dof/sources/registry.py). The ingest stage queries the registry for enabled adapters and calls `adapter.ingest(request)`.
   - Conformance logic (`adapter.conform()`) lives exclusively inside the source package, mapping provider-specific representations into canonical schemas before downstream code sees them.
2. **Game Rules Seeded from API (Invariant 2)**:
   - Game rules (squad limits, position constraints, scoring coefficients) are not hardcoded. They are dynamically parsed from FPL's `bootstrap_static` (`game_settings` and `game_config`) via [`pipeline/src/fpl_dof/rules/build.py`](file:///c:/JHH/source/fpl_dof2/pipeline/src/fpl_dof/rules/build.py) and merged with configuration overrides.
3. **No Secrets / Public Endpoints Only (Invariant 4 & 10)**:
   - The platform uses only public endpoints. No private FPL credentials or authenticated `my-team` sessions are used; squad acquisition prices are reconstructed from public transfers.
   - For third-party keys (e.g. `ODDS_API_KEY`), keys are read strictly from the environment at request time and automatically stripped from logged URLs and Bronze metadata by [`redact()`](file:///c:/JHH/source/fpl_dof2/pipeline/src/fpl_dof/sources/fetch.py#L96-L115).
4. **No Lookahead Leakage (Invariant 5)**:
   - Scraped running totals (e.g., Understat/FBref season xG/xA) are stamped with `scope="season"` and no gameweek number. They are never backfilled into historical gameweek slots, preventing future information from leaking into walk-forward backtests.
5. **Content-Addressed Determinism & Offline Purity (DP-03 & DP-11)**:
   - Bronze snapshots are compressed with `gzip.GzipFile(mtime=0, filename="")`, ensuring that identical payloads produce identical byte streams regardless of the clock.
   - The `transform` stage executes strictly offline (`request.offline=True`). If `fetcher.network_calls > 0` during transform, the run aborts immediately.

---

## 2. Ingestion Infrastructure: Fetch & Bronze Architecture

```
[ External APIs / Scrapes ]
             │
             ▼
    ┌─────────────────┐
    │  RateLimiter    │  Pacing & politeness (NFR-10)
    └────────┬────────┘
             ▼
    ┌─────────────────┐
    │  Fetcher.fetch  │ ◄── Cache Hit (age < TTL) ── Read existing payload
    └────────┬────────┘
             │ Miss / Force
             ▼
   [ Gzip mtime=0 ]
             │
             ▼
 ┌────────────────────────────────────────────────────────────────────────┐
 │ Bronze Store (Immutable Raw Snapshots)                                 │
 │ ├── bronze/<source>/<resource>/<YYYY-MM-DD>/<key>__<timestamp>.json.gz │
 │ └── bronze/<source>/<resource>/<YYYY-MM-DD>/<key>__<timestamp>.meta.json│
 └────────────────────────────────────────────────────────────────────────┘
```

### 2.1 The Shared Transport (`pipeline/src/fpl_dof/sources/fetch.py`)
Individual source adapters are prohibited from creating their own HTTP sessions or handling retries. All ingress routes through `Fetcher`:
- **Politeness & Rate-Limiting**: Enforced process-wide by [`RateLimiter`](file:///c:/JHH/source/fpl_dof2/pipeline/src/fpl_dof/sources/fetch.py#L48-L69) using `min_interval = 1.0 / requests_per_second`.
- **Retry Backoff with Jitter**: Exponential backoff (`delay = capped + uniform(-jitter, +jitter)`) handling transient network blips and 429/503 responses.
- **Cache-by-Bronze**: Bronze serves as both the raw audit log and the HTTP cache. If `cached.age_seconds() < cache_ttl_seconds` and `force_refresh=False`, the request is satisfied from disk with zero network traffic.

### 2.2 Bronze Storage Format & Lineage (`pipeline/src/fpl_dof/sources/bronze.py`)
Bronze snapshots are organized into date partitions:
`data/bronze/<source>/<resource>/<YYYY-MM-DD>/<safe_key>__<YYYYMMDDTHHMMSSZ>.<ext>.gz`

Each compressed artifact is paired with a companion JSON metadata sidecar (`.meta.json`):
- `source`, `source_version`, `resource`, `key`, `url` (redacted)
- `http_status`, `fetched_at` (UTC ISO timestamp), `run_id`
- `sha256` of the **uncompressed** payload, uncompressed byte length, `content_encoding`

---

## 3. Detailed Data Source Catalogue

The system interacts with 5 registered adapters and 4 reference/prospective datasets:

| Source Key | Kind | Provider / Origin | Acquisition Cadence | Fast Path? | Essential? | Primary Output Tables |
|---|---|---|---|---|---|---|
| `fpl` | Live | Fantasy Premier League REST API | Hourly (guard-filtered) + Daily | Yes (subset) | **Yes** | `player`, `team`, `fixture`, `gameweek`, `price_history`, `player_gameweek`, `entry_*`, `league_*` |
| `understat` | Live | Understat EPL Scrape | Daily (Ingest slow) | No | No | `player_advanced`, `player_crosswalk` (xG, xA, key passes) |
| `fbref` | Live | Sports Reference FBref Scrape | Daily (Ingest slow) | No | No | `player_advanced`, `player_crosswalk` (Defensive actions, SCA, GCA) |
| `fplarchive` | Live/Ref | Vaastav GitHub Archive Mirror | Preseason / Backfill on demand | No | No | `player_gameweek` (Historical seasons 2023–2026) |
| `oddsapi` | Live | The Odds API | Daily (Quota ledger-gated) | No | No | `team_match_expectation` (De-vigged match xG & clean sheets) |
| `fdcouk_fixtures` | External | football-data.co.uk | Pre-deadline match odds | N/A | No | Prospective harness odds |
| `fdcouk_history` | External | football-data.co.uk | Pinned reference (2023–2026) | N/A | No | Prospective model backtests |
| `fdcouk_backfill_2627` | External | football-data.co.uk | Frozen snapshot (GW1–6) | N/A | No | Historical replay verification |
| `fplcache` | External | Community FPL snapshot index | Pinned historical archive (ends GW38 25/26) | N/A | No | Model backtest calibration |

---

### Source Deep-Dives

#### 3.1 `fpl` (Official FPL API) — `pipeline/src/fpl_dof/sources/fpl/adapter.py`
- **Origin**: `https://fantasy.premierleague.com/api` (JSON REST API).
- **Ingress Schedule**:
  - *Fast Path* ([`ingest-fast.yml`](file:///c:/JHH/source/fpl_dof2/.github/workflows/ingest-fast.yml)): Scheduled hourly (`cron: "7 * * * *"`). A runtime schedule guard ([`schedule.py`](file:///c:/JHH/source/fpl_dof2/pipeline/src/fpl_dof/week/schedule.py)) decides whether to fetch based on proximity to the next deadline (ordinarily every 4 hours; hourly within 24 hours of deadline). Fetches `bootstrap_static`, `fixtures`, `set_piece_notes`, and owner team state.
  - *Slow Path* ([`ingest-slow.yml`](file:///c:/JHH/source/fpl_dof2/.github/workflows/ingest-slow.yml)): Scheduled daily at 02:23 UTC (`cron: "23 2 * * *"`). Fetches `element_summary` for all ~700 players and live event statistics.
- **Bronze Capture**:
  - `bootstrap_static` (TTL: 1 hour)
  - `fixtures` (TTL: 1 hour)
  - `element_summary` (key: `player_id`, TTL: 7 days)
  - `event_live` (key: `gw_id`, TTL: 1 hour)
  - `entry`, `entry_history`, `entry_picks`, `entry_transfers` (TTL: 1 hour)
- **Silver Transformations**:
  - Normalizes prices by dividing raw integers by `currency_divisor` (usually 10, e.g., 100 -> £10.0m).
  - Derives `season` dynamically from deadline timestamps (never hardcoded).
  - Normalizes positions to canonical codes (`GKP`, `DEF`, `MID`, `FWD`).
  - Converts timestamps to timezone-aware UTC `pd.DatetimeTZDtype`.

#### 3.2 `understat` (Understat Scrape) — `pipeline/src/fpl_dof/sources/understat/adapter.py`
- **Origin**: `https://understat.com/league/EPL`
- **Ingress Schedule**: Slow path only (once daily).
- **Robots / Posture**: Fetches and evaluates `robots.txt` via [`robots.py`](file:///c:/JHH/source/fpl_dof2/pipeline/src/fpl_dof/sources/robots.py) prior to requesting pages. *(Note: When Understat publishes `Disallow: /`, the adapter stands down cleanly, logging a warning rather than raising an unhandled failure)*.
- **Bronze Capture**: HTML stored as `epl__<timestamp>.html.gz` (TTL: 24 hours).
- **Silver Transformations**:
  - Regex extraction of embedded JavaScript JSON: `var playersData = JSON.parse('...')`.
  - Maps `xG`, `npxG`, `xA`, `shots`, and `key_passes` to `Table.PLAYER_ADVANCED` with `scope="season"`.
  - Generates crosswalk candidate records for entity resolution.

#### 3.3 `fbref` (Sports Reference FBref Scrape) — `pipeline/src/fpl_dof/sources/fbref/adapter.py`
- **Origin**: `https://fbref.com/en/comps/9/`
- **Ingress Schedule**: Slow path only (once daily, TTL: 7 days).
- **Robots / Posture**: Complies with `robots.txt`. Handles Cloudflare 403 responses gracefully as an enrichment outage without stopping the pipeline.
- **Bronze Capture**: HTML tables stored as `.html.gz`.
- **Silver Transformations**:
  - Parses `data-stat` table attributes from standard, shooting, passing, pass types, goal/shot creation, and defensive action tables.
  - Normalizes defensive threshold crossing metrics (tackles, interceptions, blocks, clearances, recoveries).
  - Emits records to `Table.PLAYER_ADVANCED` tagged with `scope="season"`.

#### 3.4 `fplarchive` (Vaastav GitHub Community Archive) — `pipeline/src/fpl_dof/sources/fplarchive/adapter.py`
- **Origin**: GitHub raw CSV releases (`vaastav/Fantasy-Premier-League`).
- **Ingress Schedule**: On demand during historical backfills (preseason model training). TTL: 1 year.
- **Bronze Capture**: Raw CSVs stored as `.csv.gz` (`merged_gw.csv.gz`, `players_raw.csv.gz`, `teams.csv.gz`).
- **Silver Transformations**:
  - **Player ID Disambiguation**: FPL reassigns integer player IDs every season. This adapter resolves players to their career-stable `code` from `players_raw.csv`.
  - **Team Code Bijective Mapping**: FPL re-indexes team IDs every year alphabetically. The adapter joins club names to FPL's permanent team `code`, ensuring cross-season team strength modeling does not corrupt club identities.
  - Preserves absent defensive statistics prior to 2025/26 as `null` rather than `0.0`.

#### 3.5 `oddsapi` (The Odds API) — `pipeline/src/fpl_dof/sources/oddsapi/adapter.py`
- **Origin**: `https://api.the-odds-api.com/v4/sports/soccer_epl/odds`
- **Ingress Schedule**: Slow path; requests gated by an on-disk monthly credit ledger. TTL: 1 hour.
- **Credential Handling**: Read from environment variable `ODDS_API_KEY`. Automatically redacted from Bronze file paths and URLs.
- **Silver Transformations**:
  - Applies Shin de-vigging algorithms in [`market.py`](file:///c:/JHH/source/fpl_dof2/pipeline/src/fpl_dof/sources/oddsapi/market.py) to convert bookmaker odds into margin-free goal expectancies and clean-sheet probabilities.
  - Outputs to `Table.TEAM_MATCH_EXPECTATION`.

---

## 4. Entity Resolution & Conformance in Silver

Multiple disparate sources are conformed into a unified tabular model in [`pipeline/src/fpl_dof/stages/transform.py`](file:///c:/JHH/source/fpl_dof2/pipeline/src/fpl_dof/stages/transform.py):

```
       Source Adapters (fpl, understat, fbref, oddsapi)
                             │
                             ▼  adapter.conform(request)
               Unresolved Conformed DataFrames
                             │
                             ▼  sources.canonicalise()
           ┌─────────────────┴─────────────────┐
           ▼                                   ▼
 ┌──────────────────────┐            ┌──────────────────────┐
 │ Entity Resolution    │            │ Field Precedence     │
 │ (resolve.py)         │            │ (precedence.py)      │
 │  1. Manual Override  │            │ Determines which     │
 │  2. Deterministic    │            │ source wins for each │
 │  3. Fuzzy Match      │            │ canonical column     │
 └─────────┬────────────┘            └──────────┬───────────┘
           │                                    │
           └─────────────────┬──────────────────┘
                             ▼
                 Deduplication (KEYS[table])
                             │
                             ▼  Pandera Schema Validation
                     Silver Parquet
```

1. **Entity Resolution ([`resolve.py`](file:///c:/JHH/source/fpl_dof2/pipeline/src/fpl_dof/sources/resolve.py))**:
   - **Tier 1 (Override)**: Checked against [`entity_overrides.yaml`](file:///c:/JHH/source/fpl_dof2/pipeline/src/fpl_dof/sources/entity_overrides.yaml). Human-reviewed mappings take absolute precedence.
   - **Tier 2 (Deterministic)**: Normalised name + club team code + position code. Zero ambiguity allowed.
   - **Tier 3 (Fuzzy)**: Token-set ratio string distance within the same club, accepting matches only if above a strict similarity threshold and clear of runner-up ambiguity.
   - **Failure Mode**: Unmatched entities are stored in `Table.PLAYER_CROSSWALK` with `match_method="unmatched"` rather than being silently dropped.
2. **Field Precedence ([`precedence.py`](file:///c:/JHH/source/fpl_dof2/pipeline/src/fpl_dof/sources/precedence.py))**:
   - Configured in `SourcesConfig.precedence`. For overlapping metrics (e.g. `expected_goals`), the configured primary source wins. Missing values fall back to secondary sources.
3. **Pandera Schema Validation ([`tables.py`](file:///c:/JHH/source/fpl_dof2/pipeline/src/fpl_dof/silver/tables.py))**:
   - Enforces strict data types, non-nullability, ranges, and primary key uniqueness on read and write. Schema violations fail the pipeline.

---

## 5. Behavior on Redundant Ingest Triggers (No Changes to Source Data)

When an ingestion workflow is triggered repeatedly with identical source data, the system exhibits deterministic, idempotent behavior across every tier:

```
Run 1 (Initial Ingest)
  Network Call ──► Writes bronze/.../<key>__T1.json.gz (sha256: ABC)
  Transform    ──► Reads T1 ──► Writes silver/.../<table_name>.parquet

Run 2 (Triggered inside TTL, e.g. 10 mins later)
  Fetcher.fetch ──► Cache Hit (age < TTL) ──► ZERO network calls
  Bronze        ──► ZERO new files written
  Transform     ──► Reads latest T1 ──► Rewrites identical Parquet (Appended tables deduped)

Run 3 (Triggered past TTL or --force-refresh, but Source Data Unchanged)
  Network Call  ──► HTTP 200 (payload unchanged, sha256: ABC)
  Bronze        ──► Writes bronze/.../<key>__T3.json.gz (mtime=0 gzip, payload sha256: ABC)
  Transform     ──► Reads T3 (identical payload)
                ──► Standard tables: Overwritten with identical Parquet rows
                ──► Appended tables: Deduped by unique keys (no duplicate rows)
```

### 5.1 Case A: Triggered Within Cache TTL
*Applies to standard hourly/cron runs when data has not expired (e.g., FPL bootstrap TTL = 1h, element summaries TTL = 7d).*
- **Network & Fetcher**: `Fetcher.fetch()` evaluates `cached.age_seconds() < ttl`. Returns cached snapshot. `fetcher.cache_hits` increments; `fetcher.network_calls == 0`.
- **Bronze Layer**: **Zero filesystem writes**. No new `.json.gz` or `.meta.json` files are created.
- **Transform Layer**: Reads the existing latest snapshot. Conformance and validation produce identical DataFrames.
- **Silver Layer**:
  - Non-appended tables are rewritten with identical rows.
  - Appended tables (`price_history`, `player_gameweek`) execute `append_table()`, merging existing Parquet rows with the current frame and deduplicating on `["observed_at", "player_id"]` (or gameweek keys). No duplicate rows are added.

### 5.2 Case B: Triggered After Cache TTL or with `--force-refresh`
*Occurs when TTL has elapsed or `--force-refresh` is passed, but the remote server returns the exact same data.*
- **Network & Fetcher**: `Fetcher` executes a conditional HTTP GET request. The remote payload is downloaded.
- **Bronze Layer**:
  - A new snapshot file is written under today's date directory: `<key>__<new_timestamp>.json.gz`.
  - Because `BronzeStore.write` fixes `mtime=0` and leaves embedded filenames empty, the compressed bytes are deterministic.
  - The `.meta.json` records the new `fetched_at` timestamp and new `run_id`, but records the **identical `sha256` checksum** as the previous snapshot.
  - **Retention & Disk Growth**: The rolling retention script ([`retention.py`](file:///c:/JHH/source/fpl_dof2/pipeline/src/fpl_dof/retention.py)) prunes snapshots older than the configured window (e.g., 14 days) during the scheduled push to the `data` branch, preventing unbounded repository growth.
- **Transform Layer**:
  - `bronze.latest()` discovers the newly timestamped file by lexical order and reads its payload.
  - Conformance yields identical records.
- **Silver Layer**:
  - **Standard Tables (18 of 20 tables)**: [`write_table()`](file:///c:/JHH/source/fpl_dof2/pipeline/src/fpl_dof/silver/store.py#L24-L29) overwrites `<table_name>.parquet` with identical rows.
  - **Appended Tables (`price_history`, `player_gameweek`)**:
    - `player_gameweek` deduplicates on `["season", "gameweek", "player_code", "fixture_id"]` keeping the latest row. Since statistics have not changed, row count is unchanged.
    - `price_history` timestamps observations using `observed_at = request.now or utcnow()`. If triggered at a different second, a new observation row is appended for that timestamp; if deduplicated within the same observation run, `drop_duplicates(subset=["observed_at", "player_id"])` keeps exactly one row per player.
