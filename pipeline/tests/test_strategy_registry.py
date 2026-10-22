"""The strategy registry (MOD-03, DL-86, DL-87): one home for each strategy's id, label and role."""

from __future__ import annotations

import ast
import json
from pathlib import Path
from typing import Any, get_args

import pytest
import yaml

from fpl_dof.config.models import OptimiserConfig
from fpl_dof.factory import registry
from fpl_dof.factory.registry import (
    STRATEGIES_DIR,
    RegistryError,
    Role,
    champion,
    digest,
    load_registry,
    load_strategy,
    published_strategies,
    resolve_alias,
    strategies,
)
from fpl_dof.publish.contract import CONTRACT_VERSION, Contract, find_contracts_root
from fpl_dof.publish.strategies import build_strategies
from fpl_dof.stages import week

SRC = Path(registry.__file__).resolve().parents[1]
CONTRACTS = SRC.parents[2] / "contracts"


def _entry(sid: str, **over: Any) -> dict[str, Any]:
    base: dict[str, Any] = {
        "id": sid,
        "label": f"Label {sid}",
        "description": f"Description {sid}",
        "role": "challenger",
        "published": False,
        "aliases": [],
        "forecaster": {"type": "recipe", "model": "xp_v1", "training_window": "w"},
        "policy": {"captain_rule": "price_position", "plan": False},
        "requires": ["player_gameweek"],
    }
    return base | over


def _write(directory: Path, *entries: dict[str, Any]) -> Path:
    directory.mkdir(parents=True, exist_ok=True)
    for e in entries:
        (directory / f"{e['id']}.yaml").write_text(yaml.safe_dump(e), encoding="utf-8")
    return directory


def test_shipped_registry_has_exactly_one_champion_and_unique_ids() -> None:
    entries = strategies()
    assert [s.id for s in entries if s.role == "champion"] == [champion().id]
    assert len({s.id for s in entries}) == len(entries)
    assert {p.stem for p in STRATEGIES_DIR.glob("*.yaml")} == {s.id for s in entries}


def test_shipped_registry_names_the_dl87_strategies() -> None:
    assert champion().id == "c3"
    assert {s.id for s in published_strategies()} == {"c3", "c1"}
    assert {s.id for s in strategies()} == {"c3", "c1", "engine", "a", "a_odds"}


def test_aliases_resolve_legacy_keys_to_registry_ids() -> None:
    assert resolve_alias("C3") == "c3"
    assert resolve_alias("champion") == "c3"
    assert resolve_alias("challenger") == "c1"
    assert resolve_alias("A_odds") == "a_odds"
    assert resolve_alias("engine") == "engine"
    assert resolve_alias("mystery") is None


def test_digest_is_stable_and_changes_with_the_entry() -> None:
    c3 = load_strategy("c3")
    assert digest(c3) == digest(load_strategy("c3"))
    assert len(digest(c3)) == 64
    assert digest(c3) != digest(c3.model_copy(update={"label": "x"}))


def test_unknown_strategy_is_refused() -> None:
    with pytest.raises(KeyError):
        load_strategy("nope")


def test_two_champions_are_refused(tmp_path: Path) -> None:
    d = _write(tmp_path, _entry("x", role="champion"), _entry("y", role="champion"))
    with pytest.raises(RegistryError, match="exactly one champion"):
        load_registry(d)


def test_no_champion_is_refused(tmp_path: Path) -> None:
    with pytest.raises(RegistryError, match="exactly one champion"):
        load_registry(_write(tmp_path, _entry("x")))


def test_duplicate_ids_are_refused(tmp_path: Path) -> None:
    d = _write(tmp_path, _entry("x", role="champion"))
    (d / "copy.yaml").write_text(yaml.safe_dump(_entry("x")), encoding="utf-8")
    with pytest.raises(RegistryError, match="file name"):
        load_registry(d)


def test_alias_equal_to_another_id_is_refused(tmp_path: Path) -> None:
    d = _write(tmp_path, _entry("x", role="champion"), _entry("y", aliases=["x"]))
    with pytest.raises(RegistryError, match="alias"):
        load_registry(d)


def test_alias_used_twice_is_refused(tmp_path: Path) -> None:
    d = _write(tmp_path, _entry("x", role="champion", aliases=["k"]), _entry("y", aliases=["k"]))
    with pytest.raises(RegistryError, match="alias"):
        load_registry(d)


def test_published_strategy_needs_a_model_that_exists(tmp_path: Path) -> None:
    bad = _entry("y", published=True)
    bad["forecaster"] = bad["forecaster"] | {"model": "no_such_model"}
    with pytest.raises(RegistryError, match="no_such_model"):
        load_registry(_write(tmp_path, _entry("x", role="champion"), bad))


def test_unpublished_strategy_may_name_a_model_not_yet_ported(tmp_path: Path) -> None:
    later = _entry("y")
    later["forecaster"] = later["forecaster"] | {"type": "frozen", "model": "not_ported"}
    assert len(load_registry(_write(tmp_path, _entry("x", role="champion"), later))) == 2


def test_an_invalid_file_is_refused(tmp_path: Path) -> None:
    d = _write(tmp_path, _entry("x", role="champion", unexpected=1))
    with pytest.raises(RegistryError, match=r"x.yaml"):
        load_registry(d)


def test_requires_names_silver_tables(tmp_path: Path) -> None:
    d = _write(tmp_path, _entry("x", role="champion", requires=["odds_from_somewhere"]))
    with pytest.raises(RegistryError, match="odds_from_somewhere"):
        load_registry(d)


def test_champion_entry_matches_the_shipped_config_it_describes() -> None:
    # Until MOD-02/MOD-04 read the policy from the registry, the shipped optimiser config is what
    # actually runs; a drift between the two would mislabel the published champion.
    assert champion().policy.captain_rule == OptimiserConfig().captain_rule
    assert load_strategy("c1").published == OptimiserConfig().publish_challenger


def test_strategies_json_validates_and_lists_every_registry_file() -> None:
    payload = build_strategies(contract_version=CONTRACT_VERSION)
    contract = Contract(root=find_contracts_root())
    contract.validate("strategies", payload)
    roles = contract.schema("strategies")["$defs"]["strategy"]["properties"]["role"]["enum"]
    assert roles == list(get_args(Role))
    listed = {s["id"]: s for s in payload["strategies"]}
    assert set(listed) == {p.stem for p in STRATEGIES_DIR.glob("*.yaml")}
    assert payload["champion"] == "c3"
    assert listed["c3"]["digest"] == digest(load_strategy("c3"))
    assert listed["c3"]["plan"] is True and listed["c1"]["plan"] is False
    # The app reads each strategy's week and plan from here, never from a name it builds (MOD-07).
    assert listed["c3"]["artefacts"] == {"week": "week.json", "plan": "plan.json"}
    assert listed["c1"]["artefacts"] == {"week": "week_challenger.json", "plan": None}
    unpublished = [s for s in payload["strategies"] if not s["published"]]
    assert all(s["artefacts"] == {"week": None, "plan": None} for s in unpublished)


def test_week_json_names_the_champion_by_registry_id_and_digest() -> None:
    fields = week._stamp(champion())
    assert fields["model"]["id"] == "c3"
    assert fields["model"]["role"] == "champion"
    assert fields["strategy"] == {"id": "c3", "digest": digest(load_strategy("c3"))}


# --- one home: no model id or label is defined outside the registry -------------------------

#: The frozen harness keeps its own keys until MOD-06 switches it off (DL-87): its input check
#: names each frozen model's needs by harness key, and the bundle is a byte-frozen copy.
FROZEN_HARNESS = {SRC / "prospective" / "freshness.py"}


def _names() -> set[str]:
    out: set[str] = set()
    for s in strategies():
        out |= {s.id, *s.aliases}
    return out


def _module_constants(path: Path) -> set[str]:
    """String constants in module-level assignments: where a table of ids would be defined."""
    found: set[str] = set()
    for node in ast.parse(path.read_text(encoding="utf-8")).body:
        if isinstance(node, ast.Assign | ast.AnnAssign) and node.value is not None:
            for sub in ast.walk(node.value):
                if isinstance(sub, ast.Constant) and isinstance(sub.value, str):
                    found.add(sub.value)
    return found


def _all_strings(path: Path) -> set[str]:
    return {
        n.value
        for n in ast.walk(ast.parse(path.read_text(encoding="utf-8")))
        if isinstance(n, ast.Constant) and isinstance(n.value, str)
    }


def _python() -> list[Path]:
    return [
        p
        for p in SRC.rglob("*.py")
        if "factory" not in p.relative_to(SRC).parts and p not in FROZEN_HARNESS
    ]


def test_no_python_module_defines_a_strategy_id_or_alias() -> None:
    names = _names()
    offenders = {str(p.relative_to(SRC)): _module_constants(p) & names for p in _python()}
    assert {k: v for k, v in offenders.items() if v} == {}


def test_no_python_module_restates_a_strategy_label() -> None:
    labels = {s.label for s in strategies()} | {s.description for s in strategies()}
    offenders = {str(p.relative_to(SRC)): _all_strings(p) & labels for p in _python()}
    assert {k: v for k, v in offenders.items() if v} == {}


def _enums(node: Any) -> list[list[Any]]:
    if isinstance(node, dict):
        own = [node["enum"]] if isinstance(node.get("enum"), list) else []
        return own + [e for v in node.values() for e in _enums(v)]
    if isinstance(node, list):
        return [e for v in node for e in _enums(v)]
    return []


def test_no_schema_enumerates_strategy_ids_or_restates_labels() -> None:
    names = _names() - {"champion", "challenger"}  # role names, which week.json still enumerates
    labels = {s.label for s in strategies()}
    for path in CONTRACTS.rglob("*.schema.json"):
        text = path.read_text(encoding="utf-8")
        listed = {v for e in _enums(json.loads(text)) for v in e if isinstance(v, str)}
        assert not listed & names, path.name
        assert not any(f'"{label}"' in text for label in labels), path.name
