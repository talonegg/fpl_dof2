"""As-if-played stage — today's models replayed in-sample on the live season (ORC-13, DL-97).

Not part of ``run``, and not part of the backtest: it fits every published strategy once and replays
each finished gameweek through the decision engine, chips included, which is too slow for the
pipeline's 300 s (ORC-09) and would crowd the backtest's job. It runs as a job of its own in the
weekly ``backtest.yml``. It writes ``ledger/as_if_played/<run_id>.json``, which CI appends to the
``ledger`` branch and the pipeline publishes as ``as_if_played.json``.

In-sample, and labelled so: only the published artefact reads it, never the champion's grading or
a promotion.
"""

from __future__ import annotations

import json

from fpl_dof.artefacts import AS_IF_PLAYED_DIRNAME, read_rules
from fpl_dof.factory import ForecastInputs
from fpl_dof.factory.as_if_played import SETTINGS, as_if_played
from fpl_dof.factory.experiments import run_config_digest
from fpl_dof.factory.registry import published_strategies
from fpl_dof.gameweek import Phase, SilverTables, season_states
from fpl_dof.obs.logging import get_logger
from fpl_dof.pipeline import Output, StageContext, StageResult
from fpl_dof.publish.contract import CONTRACT_VERSION, Contract, find_contracts_root
from fpl_dof.publish.models_history import build_models_history
from fpl_dof.silver.store import read_table, read_table_optional
from fpl_dof.silver.tables import Table

log = get_logger(__name__)


def run(ctx: StageContext) -> StageResult:
    rules = read_rules(ctx, ctx.config.rules.season)
    season = rules.season
    silver = ctx.layout.silver
    gameweeks = read_table(silver, season, Table.GAMEWEEK)
    states = season_states(SilverTables(gameweeks), (), ctx.as_of)
    # Finished is when its points are final; Evaluated adds only the owner's squad, not read here.
    finished = [s.gameweek for s in states if s.phase in (Phase.FINISHED, Phase.EVALUATED)]
    if not finished:
        log.info("as_if_played.skipped", extra={"reason": "no gameweek is finished"})
        return StageResult(metrics={"status": "skipped", "finished": 0})

    inputs = ForecastInputs(
        players=read_table(silver, season, Table.PLAYER),
        teams=read_table(silver, season, Table.TEAM),
        fixtures=read_table(silver, season, Table.FIXTURE),
        gameweeks=gameweeks,
        history=read_table(silver, season, Table.PLAYER_SEASON_HISTORY),
        as_of=ctx.as_of,
        player_gameweek=read_table_optional(silver, season, Table.PLAYER_GAMEWEEK),
        metrics=read_table_optional(silver, season, Table.PLAYER_METRIC),
        match_odds=read_table_optional(silver, season, Table.TEAM_MATCH_EXPECTATION),
    )
    rows, unavailable, skipped = as_if_played(
        inputs,
        published_strategies(),
        rules,
        ctx.config,
        finished=finished,
        prices=read_table_optional(silver, season, Table.PRICE_HISTORY),
        chips=read_table_optional(silver, season, Table.CHIP),
    )
    document = build_models_history(
        season=season,
        rows=rows,
        unavailable=unavailable,
        provenance={
            "run_id": ctx.run_id,
            "config_digest": run_config_digest(ctx.config),
            **SETTINGS,
        },
        contract_version=CONTRACT_VERSION,
        in_sample=True,
        skipped=skipped,
    )
    Contract(root=find_contracts_root()).validate("as_if_played", document)
    path = ctx.layout.ledger / AS_IF_PLAYED_DIRNAME / f"{ctx.run_id}.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps([document], indent=1, ensure_ascii=False), encoding="utf-8")
    return StageResult(
        metrics={
            "status": "ok",
            "finished": len(finished),
            "strategies": len(rows),
            "unavailable": len(unavailable),
            "gameweeks_skipped": sum(len(v) for v in skipped.values()),
        },
        outputs=[Output(path=path, rows=len(document["gameweeks"]))],
    )
