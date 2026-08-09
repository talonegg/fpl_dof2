from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path

import pytest

from fpl_dof.config import Config, load_config
from fpl_dof.paths import DataLayout


@pytest.fixture
def isolated_env(tmp_path: Path) -> dict[str, str]:
    """An environment that pins the data root inside tmp_path and nothing else."""
    return {"FPL_DOF_DATA_DIR": str(tmp_path / "data")}


@pytest.fixture
def config(isolated_env: dict[str, str]) -> Config:
    loaded, _digest = load_config(environ=isolated_env, local_override=None)
    return loaded


@pytest.fixture
def layout(config: Config) -> Iterator[DataLayout]:
    built = DataLayout(root=config.runtime.data_dir)
    built.ensure()
    yield built
