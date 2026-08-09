from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path
from typing import ClassVar

import pytest

from fpl_dof.config.models import SourceOverride, SourcesConfig
from fpl_dof.sources.base import (
    Conformed,
    IngestReport,
    IngestRequest,
    Resource,
    SourceAdapter,
)
from fpl_dof.sources.bronze import BronzeStore
from fpl_dof.sources.fetch import Fetcher
from fpl_dof.sources.registry import (
    DuplicateSourceError,
    build,
    is_enabled,
    known,
    register,
    temporary_registry,
)


class _Alpha(SourceAdapter):
    name: ClassVar[str] = "alpha"
    version: ClassVar[str] = "1"
    summary: ClassVar[str] = "test source"
    base_url: ClassVar[str] = "https://alpha.invalid"
    resources: ClassVar[tuple[Resource, ...]] = (Resource(name="things", summary="things"),)

    def ingest(self, request: IngestRequest) -> IngestReport:
        return IngestReport(source=self.name, resources={"things": 1})

    def conform(self, request: IngestRequest) -> Conformed:
        return Conformed()


class _Beta(_Alpha):
    name: ClassVar[str] = "beta"
    enabled_by_default: ClassVar[bool] = False


@pytest.fixture
def registry() -> Iterator[None]:
    with temporary_registry((_Alpha, _Beta)):
        yield


@pytest.fixture
def fetcher(tmp_path: Path) -> Fetcher:
    from fpl_dof.config.models import HttpConfig

    return Fetcher(config=HttpConfig(), bronze=BronzeStore(tmp_path), sleep=lambda _s: None)


def test_the_real_registry_contains_at_least_one_adapter() -> None:
    assert known(), "discovery found no source adapters"


def test_duplicate_names_are_rejected(registry: None) -> None:
    class Clash(_Alpha):
        name: ClassVar[str] = "alpha"

    with pytest.raises(DuplicateSourceError):
        register(Clash)


def test_registering_the_same_class_twice_is_harmless(registry: None) -> None:
    assert register(_Alpha) is _Alpha


def test_default_enablement_is_respected(registry: None, fetcher: Fetcher) -> None:
    adapters = build(SourcesConfig(), fetcher)
    assert [a.name for a in adapters] == ["alpha"]


def test_config_can_enable_and_disable_by_name(registry: None, fetcher: Fetcher) -> None:
    config = SourcesConfig(
        overrides={
            "alpha": SourceOverride(enabled=False),
            "beta": SourceOverride(enabled=True),
        }
    )
    assert [a.name for a in build(config, fetcher)] == ["beta"]


def test_unknown_source_in_config_is_an_error(registry: None, fetcher: Fetcher) -> None:
    config = SourcesConfig(overrides={"nonesuch": SourceOverride(enabled=True)})
    with pytest.raises(KeyError, match="nonesuch"):
        build(config, fetcher)


def test_is_enabled_falls_back_to_the_class_default(registry: None) -> None:
    assert is_enabled("alpha", _Alpha, SourcesConfig()) is True
    assert is_enabled("beta", _Beta, SourcesConfig()) is False


def test_adapters_expose_their_resources(registry: None, fetcher: Fetcher) -> None:
    adapter = build(SourcesConfig(), fetcher)[0]
    assert adapter.resource("things").name == "things"
    with pytest.raises(KeyError):
        adapter.resource("absent")
    assert adapter.url_for("/x/") == "https://alpha.invalid/x/"
    assert "alpha" in repr(adapter)
