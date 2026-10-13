"""C1 shadow — per-position boosted xG model with a minutes head, P(play) x pts|play.

Port of ``backtest/vector_models.py`` (kind ``xg2``), the candidate that scored +6.70 [3.21, 9.96]
XI pts/GW over the engine in the walk-forward backtest, concentrated in 2025/26 and with 24 hits.
That is not yet a reason to ship it, so it runs as a **shadow**: every week stage fits it on
history strictly before the upcoming gameweek, lets the real transfer engine choose from its
numbers (captain by the price+position rule), and logs the XI, captain and transfers beside the
engine's own to ``shadow_c1.json``. Nothing it produces reaches ``week.json``, and any exception
it raises is caught by :func:`run_shadow_safely` so the live run cannot fail on its account.
"""

from __future__ import annotations

import json
import traceback
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

from fpl_dof.config.models import OptimiserConfig, TransferConfig
from fpl_dof.frames import as_int
from fpl_dof.obs.logging import get_logger
from fpl_dof.optimise.captain import apply_price_position_captain, price_position_scores
from fpl_dof.optimise.transfer import TransferOption, TransferRecommendation, recommend_transfers
from fpl_dof.rules.models import GameRules
from fpl_dof.squad.state import SquadState

log = get_logger(__name__)

SHADOW_FILENAME = "shadow_c1.json"
MODEL_NAME = "c1_gbm_xg_minutes"

ROLL_SRC = [
    "total_points",
    "minutes",
    "expected_goals",
    "expected_assists",
    "expected_goals_conceded",
    "starts",
    "bonus",
    "bps",
]
BASE = [
    "price",
    "was_home",
    "gp",
    "nfix",
    "min_last",
    "played_last",
    "prev_pts",
    "prev_min",
    "xgf_r",
    "xga_r",
    "opp_xgf_r",
    "opp_xga_r",
]
POSITIONS = ("GKP", "DEF", "MID", "FWD")


def build_features(history: pd.DataFrame) -> pd.DataFrame:
    """Vector's features, verbatim in substance. Every rolling value is shifted one GW."""
    d = history.copy()
    seasons = sorted(d.season.unique())
    d["sidx"] = d.season.map({s: i for i, s in enumerate(seasons)})
    d["t"] = d.sidx * 100 + d.gameweek
    d["key"] = d.season + "|" + d.player_code.astype(str)
    agg: dict[str, str] = dict.fromkeys(ROLL_SRC, "sum")
    agg.update(price="last", was_home="mean", fixture_id="count")
    keys = ["key", "season", "sidx", "gameweek", "t", "player_code", "position", "team_id"]
    g = (
        d.groupby(keys, as_index=False)
        .agg(agg)
        .rename(columns={"fixture_id": "nfix"})
        .sort_values(["key", "t"])
    )
    grouped = g.groupby("key")
    for c in ROLL_SRC:
        sh = grouped[c].shift(1)
        g[c + "_l3"] = sh.groupby(g.key).rolling(3, min_periods=1).mean().reset_index(0, drop=True)
        g[c + "_l6"] = sh.groupby(g.key).rolling(6, min_periods=1).mean().reset_index(0, drop=True)
        g[c + "_sea"] = sh.groupby(g.key).expanding().mean().reset_index(0, drop=True)
        g[c + "_ewm"] = sh.groupby(g.key).transform(
            lambda x: x.ewm(halflife=4, ignore_na=True).mean()
        )
    g["gp"] = grouped.cumcount()
    g["min_last"] = grouped["minutes"].shift(1)
    g["played_last"] = (g.min_last > 0).astype(float)
    prev = g.groupby(["sidx", "player_code"], as_index=False)[["total_points", "minutes"]].mean()
    prev["sidx"] += 1
    g = g.merge(
        prev.rename(columns={"total_points": "prev_pts", "minutes": "prev_min"}),
        on=["sidx", "player_code"],
        how="left",
    )
    fx = d.groupby(["season", "t", "fixture_id", "team_id"], as_index=False).expected_goals.sum()
    fx2 = fx.merge(fx, on=["season", "t", "fixture_id"], suffixes=("", "_o"))
    fx2 = fx2[fx2.team_id != fx2.team_id_o]
    tg = (
        fx2.groupby(["season", "t", "team_id"], as_index=False)
        .agg(xgf=("expected_goals", "sum"), xga=("expected_goals_o", "sum"))
        .sort_values("t")
    )
    for c in ["xgf", "xga"]:
        tg[c + "_r"] = tg.groupby(["season", "team_id"])[c].transform(
            lambda x: x.shift(1).ewm(halflife=6).mean()
        )
    opp = d.groupby(["season", "t", "team_id"], as_index=False).opponent_team_id.first()
    g = g.merge(opp, on=["season", "t", "team_id"], how="left")
    cols = ["season", "t", "team_id", "xgf_r", "xga_r"]
    g = g.merge(tg[cols], on=["season", "t", "team_id"], how="left")
    g = g.merge(
        tg[cols].rename(
            columns={"team_id": "opponent_team_id", "xgf_r": "opp_xgf_r", "xga_r": "opp_xga_r"}
        ),
        on=["season", "t", "opponent_team_id"],
        how="left",
    )
    g["nfix"] = g.nfix.astype(float)
    g[["prev_pts", "prev_min"]] = g[["prev_pts", "prev_min"]].fillna(-1)
    g["was_home"] = g.was_home.astype(float)
    return g


def upcoming_rows(
    players: pd.DataFrame, fixtures: pd.DataFrame, season: str, gameweek: int
) -> pd.DataFrame:
    """One outcome-less row per player per fixture in ``gameweek``: the rows to predict."""
    fx = fixtures[fixtures["gameweek"] == gameweek]
    sides = pd.concat(
        [
            fx.assign(team_id=fx.home_team_id, opponent_team_id=fx.away_team_id, was_home=True),
            fx.assign(team_id=fx.away_team_id, opponent_team_id=fx.home_team_id, was_home=False),
        ]
    )[["fixture_id", "team_id", "opponent_team_id", "was_home"]]
    roster = players.rename(columns={"code": "player_code"})[
        ["player_id", "player_code", "web_name", "position", "team_id", "price"]
    ]
    rows = roster.merge(sides, on="team_id", how="inner")
    rows["season"] = season
    rows["gameweek"] = gameweek
    for c in ROLL_SRC:
        rows[c] = np.nan
    return rows


class C1Model:
    """Per-position HistGBM classifier (plays?) x regressor (points | plays)."""

    def __init__(self) -> None:
        self.models: dict[str, Any] = {}
        self.features: list[str] = []

    def fit_predict(self, g: pd.DataFrame, t_next: int) -> pd.Series:
        from sklearn.ensemble import HistGradientBoostingClassifier, HistGradientBoostingRegressor

        roll = [c for c in g.columns if any(c.endswith(s) for s in ("_l3", "_l6", "_sea", "_ewm"))]
        self.features = BASE + roll
        train = g[(g.t < t_next) & (g.gp > 0)]
        test = g[g.t == t_next]
        out = pd.Series(0.0, index=test.index)
        kw: dict[str, Any] = {"max_iter": 200, "learning_rate": 0.05, "min_samples_leaf": 50}
        for pos in POSITIONS:
            p = train[train.position == pos]
            played = p[p.minutes > 0]
            e = test[test.position == pos]
            if e.empty or p.empty or played.empty:
                continue
            clf = HistGradientBoostingClassifier(**kw).fit(
                p[self.features], (p.minutes > 0).astype(int)
            )
            reg = HistGradientBoostingRegressor(**kw).fit(
                played[self.features], played.total_points
            )
            self.models[pos] = (clf, reg)
            out.loc[e.index] = clf.predict_proba(e[self.features])[:, 1] * reg.predict(
                e[self.features]
            )
        return pd.Series(out.to_numpy(), index=test.player_code.to_numpy())


def predict_next(
    history: pd.DataFrame, players: pd.DataFrame, fixtures: pd.DataFrame, season: str, gameweek: int
) -> dict[int, float]:
    """C1 xPts for ``gameweek`` per ``player_code``, trained on history strictly before it."""
    past = history[(history["season"] != season) | (history["gameweek"] < gameweek)]
    future = upcoming_rows(players, fixtures, season, gameweek)
    columns = [c for c in past.columns if c in future.columns]
    frame = pd.concat([past, future[columns]], ignore_index=True)
    frame["fixture_id"] = frame["fixture_id"].astype(float)
    g = build_features(frame)
    t_next = int(g[(g.season == season) & (g.gameweek == gameweek)].t.iloc[0])
    return {as_int(k): float(v) for k, v in C1Model().fit_predict(g, t_next).items()}


def _option(option: TransferOption) -> dict[str, object]:
    return {
        "transfers": option.transfers,
        "hit_points": option.hit_points,
        "moves": [
            {"out": m.player_out_id, "in": m.player_in_id, "text": m.describe()}
            for m in option.moves
        ],
        "starting": list(option.starting),
        "captain": option.captain_id,
        "vice_captain": option.vice_captain_id,
        "gross_expected_points": option.gross_expected_points,
    }


@dataclass(frozen=True)
class Challenger:
    """C1's full weekly answer: the recommendation, the xPts frame it was chosen from, and the
    price+position captain scores (None when there was no history to fit them)."""

    recommendation: TransferRecommendation
    forecast: pd.DataFrame
    captain_scores: dict[int, float] | None


def fit_challenger(
    *,
    forecast: pd.DataFrame,
    history: pd.DataFrame,
    players: pd.DataFrame,
    fixtures: pd.DataFrame,
    state: SquadState,
    rules: GameRules,
    transfer_config: TransferConfig,
    optimiser_config: OptimiserConfig,
    gameweek: int,
) -> Challenger:
    """Fit C1 on history strictly before ``gameweek`` and run the real transfer engine on it."""
    xp_by_code = predict_next(history, players, fixtures, rules.season, gameweek)
    code_of = dict(zip(players["player_id"].astype(int), players["code"].astype(int), strict=True))
    frame = forecast.copy()
    frame["xp_next"] = [xp_by_code.get(code_of.get(as_int(i), -1), 0.0) for i in frame["player_id"]]
    frame["xp_horizon"] = frame["xp_next"]
    rec = recommend_transfers(frame, state, rules, transfer_config, optimiser_config)
    scores = price_position_scores(frame, history)
    if scores is not None:
        rec = apply_price_position_captain(rec, frame, scores, optimiser_config.captain_multiplier)
    return Challenger(recommendation=rec, forecast=frame, captain_scores=scores)


def run_shadow(**kwargs: Any) -> TransferRecommendation:
    return fit_challenger(**kwargs).recommendation


def run_shadow_safely(
    *,
    gold: Path,
    run_id: str,
    gameweek: int,
    engine: TransferRecommendation,
    result: Challenger | BaseException | None = None,
    **kwargs: Any,
) -> Path | None:
    """Run C1 and log it beside the engine. Never raises: the shadow cannot fail the pipeline.

    ``result`` lets the week stage pass in a challenger it has already fitted (or the exception
    fitting it raised), so the model is trained once per run for both the log and the published
    challenger artefact.
    """
    payload: dict[str, object] = {
        "run_id": run_id,
        "gameweek": gameweek,
        "model": MODEL_NAME,
        "affects_live_recommendation": False,
        "engine": _option(engine.recommended),
    }
    try:
        if isinstance(result, BaseException):
            raise result
        shadow = (
            result.recommendation if result is not None else run_shadow(gameweek=gameweek, **kwargs)
        )
        payload.update(
            status="ok", shadow=_option(shadow.recommended), shadow_rationale=shadow.rationale
        )
    except Exception as exc:
        log.warning("shadow.c1_failed", extra={"error": repr(exc)})
        payload.update(status="failed", error=repr(exc), traceback=traceback.format_exc())
    try:
        gold.mkdir(parents=True, exist_ok=True)
        path = gold / SHADOW_FILENAME
        path.write_text(json.dumps(payload, indent=2, default=str), encoding="utf-8")
        return path
    except Exception as exc:
        log.warning("shadow.c1_unwritable", extra={"error": repr(exc)})
        return None
