from __future__ import annotations

from pathlib import Path

import pytest

from fpl_dof.config import ConfigError, load_config
from fpl_dof.config.loader import ENV_MAP, config_digest, merge_layers


def test_defaults_load_and_validate(tmp_path: Path) -> None:
    config, digest = load_config(environ={"FPL_DOF_DATA_DIR": str(tmp_path)}, local_override=None)
    assert config.runtime.env == "local"
    assert config.http.rate_limit.requests_per_second > 0
    assert len(digest) == 64


def test_environment_overrides_defaults(tmp_path: Path) -> None:
    config, _ = load_config(
        environ={
            "FPL_DOF_DATA_DIR": str(tmp_path),
            "FPL_DOF_LOG_LEVEL": "DEBUG",
            "FPL_DOF_USER_AGENT_CONTACT": "https://example.invalid/contact",
        },
        local_override=None,
    )
    assert config.runtime.log_level == "DEBUG"
    assert config.http.user_agent_contact == "https://example.invalid/contact"


def test_local_override_beats_defaults_and_loses_to_environment(tmp_path: Path) -> None:
    override = tmp_path / "local.yaml"
    override.write_text(
        "runtime:\n  log_level: WARNING\nhttp:\n  timeout_seconds: 5.0\n", encoding="utf-8"
    )

    from_file, _ = load_config(environ={"FPL_DOF_DATA_DIR": str(tmp_path)}, local_override=override)
    assert from_file.runtime.log_level == "WARNING"
    assert from_file.http.timeout_seconds == 5.0

    from_env, _ = load_config(
        environ={"FPL_DOF_DATA_DIR": str(tmp_path), "FPL_DOF_LOG_LEVEL": "ERROR"},
        local_override=override,
    )
    assert from_env.runtime.log_level == "ERROR"
    assert from_env.http.timeout_seconds == 5.0


def test_unknown_key_is_rejected_rather_than_ignored(tmp_path: Path) -> None:
    override = tmp_path / "local.yaml"
    override.write_text("http:\n  requests_per_secnd: 99\n", encoding="utf-8")
    with pytest.raises(ConfigError):
        load_config(environ={"FPL_DOF_DATA_DIR": str(tmp_path)}, local_override=override)


def test_missing_override_file_is_an_error(tmp_path: Path) -> None:
    with pytest.raises(ConfigError):
        load_config(
            environ={"FPL_DOF_DATA_DIR": str(tmp_path)},
            local_override=tmp_path / "absent.yaml",
        )


def test_data_dir_is_absolute(tmp_path: Path) -> None:
    config, _ = load_config(
        environ={"FPL_DOF_DATA_DIR": str(tmp_path / "rel")}, local_override=None
    )
    assert config.runtime.data_dir.is_absolute()


def test_digest_is_stable_and_sensitive(tmp_path: Path) -> None:
    a = merge_layers([{"runtime": {"log_level": "INFO"}}])
    b = merge_layers([{"runtime": {"log_level": "INFO"}}])
    c = merge_layers([{"runtime": {"log_level": "DEBUG"}}])
    assert config_digest(a) == config_digest(b)
    assert config_digest(a) != config_digest(c)


def test_env_map_names_are_all_prefixed() -> None:
    assert all(name.startswith("FPL_DOF_") for name in ENV_MAP)


def test_config_is_immutable(tmp_path: Path) -> None:
    config, _ = load_config(environ={"FPL_DOF_DATA_DIR": str(tmp_path)}, local_override=None)
    with pytest.raises(Exception):  # noqa: B017 - pydantic raises ValidationError on frozen set
        config.runtime.log_level = "DEBUG"  # type: ignore[misc]
