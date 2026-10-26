"""Build the realised-points corpus (ORC-04) from FPL's public endpoints.

    python scripts/realised_corpus.py --last-gameweek 7 --entries 2200570 2199075 ...
    python scripts/realised_corpus.py --last-gameweek 7 --league-entries 10

Writes contracts/conformance/realised/realised-corpus.json: one case per entry and finished
gameweek, each with FPL's own points, hit and automatic substitutions as the expected answer. The
owner's entry (FPL_DOF_TEAM_ID or --owner) comes first; the others are given by id, or taken from
the top of the mini-league (FPL_DOF_LEAGUE_ID or --league). The file's constructed cases (the
gameweek in play, LIVE-03) are written by hand, not fetched, and a rebuild keeps them. See
contracts/conformance/README.md.

Public endpoints only, never a credential (Invariant 4). Entry ids only, never a name. Serial, one
request a second, an honest User-Agent, and every response cached under data/ (gitignored), so a
rebuild re-fetches nothing. The free-transfer rules come from the pipeline's own rules config
(``fpl_dof.config.load_config``), never a literal here (Invariant 2).
"""

import argparse
import json
import os
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any

from fpl_dof.config import load_config
from fpl_dof.config.models import RulesConfig

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "contracts" / "conformance" / "realised" / "realised-corpus.json"
CACHE = ROOT / "data" / "cache" / "realised-corpus"
BASE = "https://fantasy.premierleague.com/api/"
USER_AGENT = "fpl-dof/realised-corpus (+https://github.com/talonegg/fpl_dof2)"
SECONDS_BETWEEN_REQUESTS = 1.0  # below the pipeline's own 2/s (NFR-10)


def get(path: str, cache: Path) -> Any:
    """One public endpoint, from the cache when it has been fetched before. ``None`` on a 404."""
    cached = cache / (path.strip("/").replace("/", "_") + ".json")
    if cached.exists():
        return json.loads(cached.read_text(encoding="utf-8"))
    time.sleep(SECONDS_BETWEEN_REQUESTS)
    request = urllib.request.Request(BASE + path, headers={"User-Agent": USER_AGENT})
    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            data = json.loads(response.read())
    except urllib.error.HTTPError as exc:
        if exc.code == 404:  # an entry that joined after this gameweek
            return None
        raise
    cache.mkdir(parents=True, exist_ok=True)
    cached.write_text(json.dumps(data), encoding="utf-8")
    return data


def free_transfers(history: dict[str, Any], rules: RulesConfig) -> dict[int, int | None]:
    """Gameweek -> free transfers at its deadline. The first gameweek's transfers are unlimited.

    A chip that makes transfers free keeps the banked ones (the corpus input only)."""
    chips = {c["event"]: c["name"] for c in history["chips"]}
    earned = rules.transfers.free_transfers_per_gameweek
    cap = rules.transfers.max_free_transfers
    out: dict[int, int | None] = {}
    banked: int | None = None
    for row in history["current"]:
        gameweek = row["event"]
        out[gameweek] = banked
        if banked is None:
            banked = earned
        elif chips.get(gameweek) in rules.chips.transfers_free_with:
            banked = min(cap, banked + earned)
        else:
            banked = min(cap, max(banked - row["event_transfers"], 0) + earned)
    return out


def fixtures(live: dict[int, Any], player_id: int) -> list[list[int]]:
    """[minutes, points] per fixture, from the live endpoint's per-fixture ``explain``."""
    element = live.get(player_id) or {}
    return [
        [
            sum(s["value"] for s in ex["stats"] if s["identifier"] == "minutes"),
            sum(s["points"] for s in ex["stats"]),
        ]
        for ex in element.get("explain", [])
    ]


def case(
    entry: int,
    gameweek: int,
    picks: dict[str, Any],
    live: dict[int, Any],
    position: dict[int, str],
    free: int | None,
    owner: int,
) -> dict[str, Any]:
    ordered = sorted(picks["picks"], key=lambda p: p["position"])
    # A finished gameweek's picks are the XI after substitution: undo them, last first.
    slot = {p["element"]: i for i, p in enumerate(ordered)}
    for sub in reversed(picks["automatic_subs"]):
        a, b = slot[sub["element_in"]], slot[sub["element_out"]]
        ordered[a], ordered[b] = ordered[b], ordered[a]
        slot[ordered[a]["element"]], slot[ordered[b]["element"]] = a, b

    ids = [p["element"] for p in ordered]
    played = {i for i in ids if sum(m for m, _ in fixtures(live, i)) > 0}
    captain = next(p["element"] for p in ordered if p["is_captain"])
    vice = next(p["element"] for p in ordered if p["is_vice_captain"])
    subs = [[s["element_out"], s["element_in"]] for s in picks["automatic_subs"]]
    history = picks["entry_history"]

    tags = set()
    if subs:
        tags.add("auto-substitution")
    if any(position[out] == "GKP" for out, _ in subs):
        tags.add("reserve-goalkeeper")
    subbed_in = {sub for _, sub in subs}
    bench = ids[12:]
    if any(
        b in played and b not in subbed_in
        for sub in subbed_in
        if sub in bench
        for b in bench[: bench.index(sub)]
    ):
        tags.add("formation-skip")
    if captain not in played:
        tags.add("captain-did-not-play")
        if vice in played:
            tags.add("vice")
    if any(len(fixtures(live, i)) > 1 for i in ids):
        tags.add("dgw")
    if any(not fixtures(live, i) for i in ids):
        tags.add("blank")
    if picks["active_chip"]:
        tags.add(picks["active_chip"])
    if history["event_transfers_cost"]:
        tags.add(f"hit{history['event_transfers_cost']}")

    return {
        "name": f"owner-gw{gameweek}" if entry == owner else f"entry-{entry}-gw{gameweek}",
        "tags": sorted(tags),
        "entry_id": entry,
        "gameweek": gameweek,
        "chip": picks["active_chip"],
        "transfers": history["event_transfers"],
        "free_transfers": free,
        "captain": captain,
        "vice_captain": vice,
        "picks": [
            {"player_id": i, "position": position[i], "fixtures": fixtures(live, i)} for i in ids
        ],
        "expected": {
            "points": history["points"],
            "transfers_cost": history["event_transfers_cost"],
            "automatic_subs": subs,
        },
    }


def render(cases: list[dict[str, Any]]) -> str:
    """One line per pick, so a reviewer can read a case."""
    head_keys = (
        "name",
        "tags",
        "from",
        "why",
        "entry_id",
        "gameweek",
        "chip",
        "transfers",
        "free_transfers",
        "captain",
        "vice_captain",
    )
    lines = [
        "{",
        ' "about": "Real 2026/27 entries scored by FPL, and in-play cases constructed from them.'
        ' See contracts/conformance/README.md.",',
        ' "cases": [',
    ]
    for n, c in enumerate(cases):
        head = json.dumps({k: c[k] for k in head_keys if k in c})[1:-1]
        lines += [f"  {{{head},", '   "picks": [']
        lines += [
            "    " + json.dumps(p) + ("," if i < len(c["picks"]) - 1 else "")
            for i, p in enumerate(c["picks"])
        ]
        lines += ["   ],", '   "expected": ' + json.dumps(c["expected"])]
        lines.append("  }" + ("," if n < len(cases) - 1 else ""))
    return "\n".join([*lines, " ]", "}"]) + "\n"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--owner", type=int, default=os.environ.get("FPL_DOF_TEAM_ID"))
    parser.add_argument("--league", type=int, default=os.environ.get("FPL_DOF_LEAGUE_ID"))
    parser.add_argument("--entries", type=int, nargs="*", help="other entry ids, by id")
    parser.add_argument("--league-entries", type=int, default=10, help="else the league's top N")
    parser.add_argument("--last-gameweek", type=int, required=True)
    parser.add_argument("--cache", type=Path, default=CACHE)
    parser.add_argument("--out", type=Path, default=OUT)
    args = parser.parse_args()
    if args.owner is None:
        parser.error("give --owner or set FPL_DOF_TEAM_ID")

    boot = get("bootstrap-static/", args.cache)
    short = {t["id"]: t["singular_name_short"] for t in boot["element_types"]}
    position = {e["id"]: short[e["element_type"]] for e in boot["elements"]}
    finished = [e["id"] for e in boot["events"] if e["finished"] and e["id"] <= args.last_gameweek]

    others = args.entries
    if others is None:
        if args.league is None:
            parser.error("give --entries, or --league / FPL_DOF_LEAGUE_ID")
        standings = get(f"leagues-classic/{args.league}/standings/", args.cache)
        others = [r["entry"] for r in standings["standings"]["results"]]
        others = [e for e in others if e != args.owner][: args.league_entries]

    rules = load_config()[0].rules
    cases: list[dict[str, Any]] = []
    for entry in sorted({args.owner, *others}):
        history = get(f"entry/{entry}/history/", args.cache)
        free = free_transfers(history, rules)
        for gameweek in finished:
            picks = get(f"entry/{entry}/event/{gameweek}/picks/", args.cache)
            if picks is None:
                continue
            live = {e["id"]: e for e in get(f"event/{gameweek}/live/", args.cache)["elements"]}
            found = case(entry, gameweek, picks, live, position, free.get(gameweek), args.owner)
            if entry == args.owner or found["tags"]:  # an untagged case adds nothing to test
                cases.append(found)

    if args.out.exists():  # the constructed cases are hand-written: a rebuild keeps them
        kept = json.loads(args.out.read_text(encoding="utf-8"))["cases"]
        cases += [c for c in kept if "constructed" in c["tags"]]
    args.out.write_text(render(cases), encoding="utf-8")
    print(f"{len(cases)} cases -> {args.out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
