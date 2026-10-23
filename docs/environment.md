# Environment variables

Every variable the pipeline reads. Defaults live in `pipeline/src/fpl_dof/config/defaults/`; a
commented template is [`.env.example`](../.env.example).

| Variable | Purpose | Secret | Example |
| --- | --- | --- | --- |
| `FPL_DOF_ENV` | Execution context: `local` or `ci` | No | `local` |
| `FPL_DOF_DATA_DIR` | Override the data root (default `<repo>/data`) | No | `C:\JHH\data\fpl_dof` |
| `FPL_DOF_LOG_LEVEL` | Logging verbosity | No | `INFO` |
| `FPL_DOF_USER_AGENT_CONTACT` | Honest client identification (NFR-10) | No | `https://github.com/talonegg/fpl_dof2` |
| `FPL_DOF_TIMEZONE` | Local rendering zone; storage stays UTC ([DL-11](decisions/DL-11.md)) | No | `Australia/Sydney` |
| `FPL_DOF_TRIGGER` | What started the run, stamped on every advice: `schedule`, `change:<kinds>`, `manual` or `day-before` ([DL-94](decisions/DL-94.md)). `pipeline.yml` sets it from its typed dispatch inputs, as the guard read them (ORC-02) | No | `manual` |
| `FPL_DOF_TEAM_ID` | The owner's FPL entry ID | No — public | `1234567` |
| `FPL_DOF_LEAGUE_ID` | Mini-league for rival analysis. Optional; unset is the normal state ([DL-40](decisions/DL-40.md)) | No | `987654` |
| `FPL_DOF_CONFIG_FILE` | An extra config layer; CI's backtest uses `config/ci-backtest.yaml` ([DL-68](decisions/DL-68.md)) | No | `config/ci-backtest.yaml` |
| `FPL_DOF_MODELS_SOURCE_DIR` | Where CI extracts the frozen [prospective](../prospective/README.md) record for the models page | No | `prospective-record` |
| `ODDS_API_KEY` | Bookmaker odds provider ([DL-59](decisions/DL-59.md)) | **Yes** | — |
| `FPL_DOF_ODDS_CREDIT_BUDGET` | Monthly request cap, enforced in the adapter | No | `450` |

**Handling.** Non-secrets go in a gitignored `.env` locally. The one secret, `ODDS_API_KEY`, goes in
`.env` locally, never in a settings file, never in the client bundle (NFR-13). The Odds API is off by
default (PIPE-09), so no workflow passes the key; the Actions secret can stay unset. The secret-scan
hook in `.claude/hooks/` guards commits.

**In CI.** `FPL_DOF_TEAM_ID` and `FPL_DOF_LEAGUE_ID` are repository **variables**, not secrets and
not committed config, and reach the ingest workflows as well as `pipeline.yml`, because the entry is
fetched at ingest ([DL-69](decisions/DL-69.md)). Both IDs can also be entered in the app's
`/settings` view, which keeps them in browser `localStorage` only ([DL-44](decisions/DL-44.md)).
Nothing about the owner's identity is committed, ever (Invariants 8 and 10, NFR-11).

**Web build.** `VITE_FPL_PASSWORD_HASH` comes from the `FPL_PASSWORD_HASH` secret in `deploy.yml`;
see the [README](../README.md#password-gate).
