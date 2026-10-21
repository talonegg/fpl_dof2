# Planning archive

Closed releases, their epics, and planning documents that are no longer live, kept with their text unchanged; only
links were re-pointed when they moved (DL-74). They are records: cite them, never update them. The
live register is [`../epics/README.md`](../epics/README.md).

`docs/.rgignore` leaves this folder out of a plain search. Search it on purpose:
`rg "D-25" docs/planning/archive`.

## R1.0 — the first build

Epics E0–E14, built 2026-08-09 to 2026-10. E8 stays live as the ongoing in-season monitoring epic, in `../epics/`.

| Epic | Main decisions |
| --- | --- |
| [E0](R1.0/E0-steel-thread-gw1.md) — Steel thread to the GW1 squad | DL-17 to DL-20 |
| [E1](R1.0/E1-weekly-operating-loop.md) — Weekly operating loop | |
| [E2](R1.0/E2-data-platform.md) — Data platform hardening | |
| [E3](R1.0/E3-expected-points-engine.md) — Expected points engine | DL-21, DL-22 |
| [E4](R1.0/E4-decision-engine.md) — Decision engine | DL-24 to DL-26, DL-28 |
| [E5](R1.0/E5-external-sources.md) — External data sources | DL-27, DL-29, DL-31 to DL-34 |
| [E6](R1.0/E6-web-application.md) — Web application | DL-35 to DL-41 |
| [E7](R1.0/E7-automation-and-hosting.md) — Automation and hosting | DL-42 |
| [E9](R1.0/E9-forecast-delivery-and-backtest-fidelity.md) — Forecast delivery and backtest fidelity | DL-46 |
| [E10](R1.0/E10-discrimination-at-the-head.md) — Discrimination at the head | DL-47 to DL-54 |
| [E11](R1.0/E11-fixture-difficulty-and-market-signal.md) — Fixture difficulty and market signal | DL-55 to DL-61 |
| [E12](R1.0/E12-data-widening-for-priors.md) — Data widening for priors | DL-50, DL-62, DL-63 |
| [E13](R1.0/E13-runtime-personalisation-ids.md) — Runtime personalisation (team/league IDs) | DL-64 |
| [E14](R1.0/E14-recommendation-ranking-and-hindsight-oracle.md) — Recommendation ranking and hindsight oracle | DL-72, DL-73 |

Each epic's own Status line records its outcome; [the decision index](../../decisions/README.md#index)
lists every entry.

## R1.1.0 — the data pipeline uplift

PIPE-01 … PIPE-14, built 2026-10-17 to 2026-10-19, remediated by REM-01 … REM-11 and tagged
2026-10-21; its last box was verified on `main` in R1.1.1.

| Plan | Main decisions |
| --- | --- |
| [Data pipeline backlog](R1.1.0/R1.1.0-data-pipeline-backlog.md) — PIPE-01 … PIPE-14 and the remediation plan | DL-79, DL-81 to DL-85 |

## Other planning documents

| Document | What it was | Why archived |
| --- | --- | --- |
| [R1.0/README.md](R1.0/README.md) | R1.0's epic register: sequencing rationale, estimates, guardrails, the E9–E13 programme | Every epic in it but E8 is closed; the live register is [`../epics/README.md`](../epics/README.md) |
| [R1.0/INPUTS-REQUIRED.md](R1.0/INPUTS-REQUIRED.md) | What the build needed from the owner, by epic | Answered, but for §7, the timezone finding, which is [DL-11](../../decisions/DL-11.md), still Proposed. Environment variables moved to [`docs/environment.md`](../../environment.md) |
| [05-model-improvement-plan.md](05-model-improvement-plan.md) | Post-backtest research plan: gated experiments X1–X6, F1–F5, D1–D5 | Executed as E9–E13 (DL-43, DL-45) |
| [02-superseded-sections.md](02-superseded-sections.md) | The project plan's phase plan, milestones, GW1 decision and estimates | Superseded by the epics (DL-10) |
| [ai/](ai/README.md) | The AI tooling plan: CLAUDE.md, skills, agents, hooks | Implemented 2026-08-09. The hooks cite it for their design rationale (H3, H4) |
