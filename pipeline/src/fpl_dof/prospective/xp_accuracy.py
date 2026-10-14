"""Per-player xP accuracy scoring (Alchemy's design, research/fpl-xp-accuracy-scoring.md).

Pure: no I/O, no clock. Callers hand in each model's saved full-pool xP for one gameweek plus the
actual points, and get back rows for ``xp_scores.csv``; ``paired`` and ``calibration`` summarise a
whole season of those rows. This scores *forecast accuracy* only. It never touches a decision.

Population (paired): one row per (GW, player) that **every** model priced and FPL listed at the
deadline. Zero-minute players stay in (as the reference run does). Blank-GW flagging is not
implemented: the saved xP files carry no fixture count. Subsets: ``all``; ``top50_union`` (union
of each model's top-50 by xP that GW, so the comparison stays paired); ``avail_prior`` (FPL
chance of playing >= 0.75 at the deadline, a model-agnostic prior-availability split; empty when
no deadline availability was saved, as in the 2023/24-2025/26 backtest).
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping, Sequence
from typing import Any

import numpy as np
import pandas as pd

MODELS: tuple[str, ...] = ("engine", "C3", "C1", "A", "A_odds")
SUBSETS: tuple[str, ...] = ("all", "top50_union", "avail_prior")
TOP_K = 50
AVAIL_PRIOR_MIN = 0.75
SCORE_FIELDS: tuple[str, ...] = (
    "season", "gw", "model", "subset", "n_rows", "n_dropped", "mae", "mse", "rmse", "bias",
    "spearman_gw_pos", "zero_min_mean_xp", "xp_file_sha256", "scored_at",
)  # fmt: skip
PAIRED_FIELDS: tuple[str, ...] = (
    "season", "subset", "metric", "model", "comparator", "family", "n_gw", "mean_delta", "sd_delta",
    "p_signflip", "p_holm",
)  # fmt: skip
#: Pre-registered (prospective/PREREG_C1_vs_C3.md). Primary: C1 vs C3 on all-player MAE.
PRIMARY = ("C1", "C3")
SECONDARY = (("engine", "C3"), ("A", "C1"), ("A_odds", "C1"))
CAL_BINS: tuple[float, ...] = (-np.inf, 0.5, 1, 2, 3, 4, 5, 6, 8, np.inf)


def population(
    xp: Mapping[str, pd.DataFrame],
    actual: pd.DataFrame,
    listed: Iterable[int] | None = None,
) -> tuple[pd.DataFrame, dict[str, int]]:
    """Paired frame (player, position, actual, minutes, avail?, one xP column per model).

    ``xp[model]`` has ``player``, ``position``, ``xp``; ``actual`` has ``player``, ``actual``,
    ``minutes`` and optionally ``avail``. Returns the frame and rows dropped per model (rows that
    model priced but are outside the common set).
    """
    if not xp:
        raise ValueError("no models to score")
    keys: set[int] | None = {int(p) for p in listed} if listed is not None else None
    for d in xp.values():
        ids = set(d["player"].astype(int))
        keys = ids if keys is None else keys & ids
    assert keys is not None
    keys &= set(actual["player"].astype(int))
    first = next(iter(xp.values()))
    base = first[["player", "position"]].copy()
    base["player"] = base["player"].astype(int)
    base = base[base["player"].isin(keys)].drop_duplicates("player")
    acols = ["player", "actual", "minutes"] + (["avail"] if "avail" in actual.columns else [])
    a = actual[acols].copy()
    a["player"] = a["player"].astype(int)
    out = base.merge(a, on="player", how="inner")
    for m, d in xp.items():
        s = d[["player", "xp"]].copy()
        s["player"] = s["player"].astype(int)
        out = out.merge(s.rename(columns={"xp": m}), on="player", how="left")
    dropped = {m: len(set(d["player"].astype(int)) - set(out["player"])) for m, d in xp.items()}
    return out, dropped


def subsets(pop: pd.DataFrame, models: Sequence[str]) -> dict[str, pd.DataFrame]:
    ids: set[int] = set()
    for m in models:
        ids |= set(pop.nlargest(TOP_K, m)["player"])
    out = {"all": pop, "top50_union": pop[pop["player"].isin(ids)]}
    out["avail_prior"] = (
        pop[pop["avail"] >= AVAIL_PRIOR_MIN] if "avail" in pop.columns else pop.iloc[0:0]
    )
    return out


def _spearman_by_pos(df: pd.DataFrame, col: str) -> float:
    vals = []
    for _, g in df.groupby("position"):
        if g[col].nunique() > 1 and g["actual"].nunique() > 1:
            vals.append(g[col].rank().corr(g["actual"].rank()))
    return float(np.mean(vals)) if vals else float("nan")


def score_gw(
    *,
    season: str,
    gw: int,
    xp: Mapping[str, pd.DataFrame],
    actual: pd.DataFrame,
    listed: Iterable[int] | None = None,
    xp_sha256: Mapping[str, str] | None = None,
    scored_at: str = "",
) -> list[dict[str, Any]]:
    """One ``xp_scores.csv`` row per (model, subset) for one gameweek."""
    pop, dropped = population(xp, actual, listed)
    models = list(xp)
    rows = []
    for name, sub in subsets(pop, models).items():
        for m in models:
            e = sub[m] - sub["actual"]
            n = len(sub)
            zm = sub.loc[sub["minutes"] == 0, m]
            rows.append(
                {
                    "season": season,
                    "gw": int(gw),
                    "model": m,
                    "subset": name,
                    "n_rows": n,
                    "n_dropped": dropped[m],
                    "mae": float(e.abs().mean()) if n else float("nan"),
                    "mse": float((e**2).mean()) if n else float("nan"),
                    "rmse": float(np.sqrt((e**2).mean())) if n else float("nan"),
                    "bias": float(e.mean()) if n else float("nan"),
                    "spearman_gw_pos": _spearman_by_pos(sub, m) if n else float("nan"),
                    "zero_min_mean_xp": float(zm.mean()) if len(zm) else float("nan"),
                    "xp_file_sha256": (xp_sha256 or {}).get(m, ""),
                    "scored_at": scored_at,
                }
            )
    return rows


def signflip_p(x: np.ndarray, draws: int = 20000, seed: int = 0) -> float:
    x = np.asarray(x, dtype=float)
    if len(x) == 0:
        return float("nan")
    rng = np.random.default_rng(seed)
    s = rng.choice([-1.0, 1.0], size=(draws, len(x)))
    obs = abs(x.mean())
    return float(((np.abs((s * x).mean(axis=1)) >= obs - 1e-12).sum() + 1) / (draws + 1))


def holm(ps: Sequence[float]) -> list[float]:
    idx = [i for i in np.argsort(ps) if not np.isnan(ps[i])]
    out = [float("nan")] * len(ps)
    run = 0.0
    for k, i in enumerate(idx):
        run = max(run, min(1.0, (len(idx) - k) * ps[i]))
        out[i] = run
    return out


def paired(scores: pd.DataFrame, metric: str = "mae", draws: int = 20000) -> list[dict[str, Any]]:
    """Per-GW paired differences (model - comparator) on one metric, sign-flip test over GWs.

    Holm is applied within each (season, subset) across the pre-registered primary + secondary
    comparisons; the primary is also reported alone as its own family.
    """
    out: list[dict[str, Any]] = []
    for (season, subset), g in scores.groupby(["season", "subset"], sort=True):
        w = g.pivot_table(index="gw", columns="model", values=metric, aggfunc="first")
        fam: list[dict[str, Any]] = []
        for kind, pairs in (("primary", (PRIMARY,)), ("secondary", SECONDARY)):
            for m, c in pairs:
                if m not in w or c not in w:
                    continue
                d = (w[m] - w[c]).dropna().to_numpy()
                fam.append(
                    {
                        "season": season, "subset": subset, "metric": metric, "model": m,
                        "comparator": c, "family": kind, "n_gw": len(d),
                        "mean_delta": float(d.mean()) if len(d) else float("nan"),
                        "sd_delta": float(d.std(ddof=1)) if len(d) > 1 else float("nan"),
                        "p_signflip": signflip_p(d, draws),
                    }
                )  # fmt: skip
        adj = holm([r["p_signflip"] for r in fam])
        for r, p in zip(fam, adj, strict=True):
            r["p_holm"] = r["p_signflip"] if r["family"] == "primary" else p
        out += fam
    return out


def calibration(
    pop_by_gw: Iterable[tuple[str, int, pd.DataFrame]], models: Sequence[str]
) -> list[dict[str, Any]]:
    """Mean xP vs mean actual by xP bucket, all players (diagnostic, no tests)."""
    frames = [p.assign(season=s, gw=gw) for s, gw, p in pop_by_gw]
    if not frames:
        return []
    d = pd.concat(frames, ignore_index=True)
    rows = []
    for season, ds in d.groupby("season"):
        for m in models:
            if m not in ds:
                continue
            c = ds.groupby(pd.cut(ds[m], list(CAL_BINS)), observed=True).agg(
                n=(m, "size"), mean_xp=(m, "mean"), mean_actual=("actual", "mean")
            )
            for b, r in c.iterrows():
                rows.append(
                    {"season": season, "model": m, "bucket": str(b), "n": int(r["n"]),
                     "mean_xp": float(r["mean_xp"]), "mean_actual": float(r["mean_actual"])}
                )  # fmt: skip
    return rows
