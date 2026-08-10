"""Layered configuration loading.

Three layers, lowest precedence first:

1. Committed YAML defaults packaged with the code (``config/defaults/*.yaml``).
2. A gitignored local override file — ``config/local.yaml`` at the repo root, or wherever
   ``FPL_DOF_CONFIG_FILE`` points.
3. ``FPL_DOF_*`` environment variables, for the handful of settings CI and shells need to set.

The merged mapping is validated once into :class:`~fpl_dof.config.models.Config`. A digest of that
mapping goes into the run manifest so any run can be reproduced from its recorded inputs (DP-11).
"""

from __future__ import annotations

import copy
import hashlib
import json
import os
from collections.abc import Mapping, MutableMapping
from pathlib import Path
from typing import Any

import yaml

from fpl_dof.config.models import Config
from fpl_dof.paths import DataLayout, default_data_dir, find_repo_root

DEFAULTS_DIR = Path(__file__).parent / "defaults"

#: Environment variable -> dotted path into the config mapping.
#: Kept explicit rather than derived, so ``rg FPL_DOF_`` finds every supported variable.
ENV_MAP: dict[str, tuple[str, ...]] = {
    "FPL_DOF_ENV": ("runtime", "env"),
    "FPL_DOF_DATA_DIR": ("runtime", "data_dir"),
    "FPL_DOF_LOG_LEVEL": ("runtime", "log_level"),
    "FPL_DOF_TIMEZONE": ("runtime", "timezone"),
    "FPL_DOF_USER_AGENT_CONTACT": ("http", "user_agent_contact"),
    "FPL_DOF_TEAM_ID": ("entry", "team_id"),
}

LOCAL_OVERRIDE_ENV = "FPL_DOF_CONFIG_FILE"
LOCAL_OVERRIDE_NAME = "config/local.yaml"


class ConfigError(RuntimeError):
    """Configuration could not be loaded or did not validate."""


def _deep_merge(base: MutableMapping[str, Any], overlay: Mapping[str, Any]) -> None:
    """Recursively merge ``overlay`` into ``base`` in place. Scalars and lists replace wholesale."""
    for key, value in overlay.items():
        existing = base.get(key)
        if isinstance(existing, MutableMapping) and isinstance(value, Mapping):
            _deep_merge(existing, value)
        else:
            base[key] = copy.deepcopy(value)


def _read_yaml(path: Path) -> Mapping[str, Any]:
    try:
        text = path.read_text(encoding="utf-8")
    except OSError as exc:
        raise ConfigError(f"could not read config file {path}: {exc}") from exc
    try:
        loaded = yaml.safe_load(text)
    except yaml.YAMLError as exc:
        raise ConfigError(f"{path} is not valid YAML: {exc}") from exc
    if loaded is None:
        return {}
    if not isinstance(loaded, Mapping):
        raise ConfigError(f"{path} must contain a mapping at the top level, got {type(loaded)}")
    return loaded


def _set_path(target: MutableMapping[str, Any], dotted: tuple[str, ...], value: Any) -> None:
    cursor: MutableMapping[str, Any] = target
    for key in dotted[:-1]:
        child = cursor.get(key)
        if not isinstance(child, MutableMapping):
            child = {}
            cursor[key] = child
        cursor = child
    cursor[dotted[-1]] = value


def default_layers(
    *,
    defaults_dir: Path | None = None,
    local_override: Path | None = None,
    environ: Mapping[str, str] | None = None,
) -> list[Mapping[str, Any]]:
    """Resolve the three layers, in precedence order, without merging them.

    Exposed separately so tests can assert on what each layer contributed.
    """
    env = os.environ if environ is None else environ
    layers: list[Mapping[str, Any]] = []

    directory = defaults_dir or DEFAULTS_DIR
    for path in sorted(directory.glob("*.yaml")):
        layers.append(_read_yaml(path))

    override = local_override
    if override is None:
        from_env = env.get(LOCAL_OVERRIDE_ENV)
        if from_env:
            override = Path(from_env)
        else:
            root = find_repo_root()
            if root is not None:
                candidate = root / LOCAL_OVERRIDE_NAME
                override = candidate if candidate.exists() else None
    if override is not None:
        if not override.exists():
            raise ConfigError(f"config override file does not exist: {override}")
        layers.append(_read_yaml(override))

    env_layer: dict[str, Any] = {}
    for variable, dotted in ENV_MAP.items():
        raw = env.get(variable)
        if raw is not None and raw != "":
            _set_path(env_layer, dotted, raw)
    if env_layer:
        layers.append(env_layer)

    return layers


def merge_layers(layers: list[Mapping[str, Any]]) -> dict[str, Any]:
    merged: dict[str, Any] = {}
    for layer in layers:
        _deep_merge(merged, layer)
    return merged


def config_digest(merged: Mapping[str, Any]) -> str:
    """Stable SHA-256 over the merged configuration, for the run manifest."""
    canonical = json.dumps(merged, sort_keys=True, default=str, separators=(",", ":"))
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def load_config(
    *,
    defaults_dir: Path | None = None,
    local_override: Path | None = None,
    environ: Mapping[str, str] | None = None,
) -> tuple[Config, str]:
    """Load, merge and validate configuration. Returns the config and its digest."""
    merged = merge_layers(
        default_layers(
            defaults_dir=defaults_dir,
            local_override=local_override,
            environ=environ,
        )
    )
    merged.setdefault("runtime", {})
    runtime = merged["runtime"]
    if not isinstance(runtime, MutableMapping):
        raise ConfigError("runtime section must be a mapping")
    if not runtime.get("data_dir"):
        runtime["data_dir"] = str(default_data_dir())
    runtime["data_dir"] = str(Path(str(runtime["data_dir"])).expanduser().resolve())

    digest = config_digest(merged)
    try:
        config = Config.model_validate(merged)
    except Exception as exc:  # pydantic ValidationError, re-raised with context
        raise ConfigError(f"configuration did not validate: {exc}") from exc
    return config, digest


def layout_for(config: Config) -> DataLayout:
    return DataLayout(root=config.runtime.data_dir)
