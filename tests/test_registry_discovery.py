"""Unit tests for `arena.registry.discovery.discover_agents`."""

from __future__ import annotations

from pathlib import Path

import pytest

from arena.models.manifest import AgentFramework
from arena.registry.discovery import (
    AgentSource,
    RegistryLoadError,
    discover_agents,
)

FIXTURES_DIR = Path(__file__).parent / "fixtures" / "registry"
MIXED_OFFICIAL = FIXTURES_DIR / "mixed" / "official"
MIXED_COMMUNITY = FIXTURES_DIR / "mixed" / "community"
DUPLICATE_OFFICIAL = FIXTURES_DIR / "duplicate" / "official"
DUPLICATE_COMMUNITY = FIXTURES_DIR / "duplicate" / "community"
COMMUNITY_COMMAND = FIXTURES_DIR / "community_command" / "community"


def test_empty_registry_reports_zero_without_error(tmp_path: Path) -> None:
    registry = discover_agents(tmp_path / "official", tmp_path / "community")

    assert len(registry) == 0
    assert registry.filter() == []


def test_empty_existing_directories_report_zero(tmp_path: Path) -> None:
    official = tmp_path / "official"
    community = tmp_path / "community"
    official.mkdir()
    community.mkdir()

    registry = discover_agents(official, community)

    assert len(registry) == 0


def test_mixed_official_and_community_agents_discovered() -> None:
    registry = discover_agents(MIXED_OFFICIAL, MIXED_COMMUNITY)

    ids = {agent.manifest.id for agent in registry.agents}
    assert ids == {"agent-alpha", "agent-beta", "agent-gamma"}

    sources = {agent.manifest.id: agent.source for agent in registry.agents}
    assert sources["agent-alpha"] == AgentSource.OFFICIAL
    assert sources["agent-beta"] == AgentSource.COMMUNITY
    assert sources["agent-gamma"] == AgentSource.COMMUNITY


def test_duplicate_id_across_official_and_community_raises() -> None:
    with pytest.raises(RegistryLoadError, match="duplicate agent id 'agent-dup-id'"):
        discover_agents(DUPLICATE_OFFICIAL, DUPLICATE_COMMUNITY)


def test_community_command_entrypoint_is_rejected(tmp_path: Path) -> None:
    # A community submission must run inside a container; a 'command'
    # entrypoint (executed as an Arena-host subprocess by ProcessRunner) is
    # rejected at discovery, even though it is a schema-valid manifest.
    with pytest.raises(RegistryLoadError, match="must use a 'docker' entrypoint"):
        discover_agents(tmp_path / "official", COMMUNITY_COMMAND)


def test_official_command_entrypoint_is_allowed(tmp_path: Path) -> None:
    # The container requirement applies only to community submissions; official
    # agents may (and do) use 'command' entrypoints. The same manifest that is
    # rejected under the community root loads fine under the official root.
    registry = discover_agents(COMMUNITY_COMMAND, tmp_path / "community")

    assert {agent.manifest.id for agent in registry.agents} == {"host-subprocess-agent"}


def test_filter_by_framework() -> None:
    registry = discover_agents(MIXED_OFFICIAL, MIXED_COMMUNITY)

    raw_python_agents = registry.filter(framework=AgentFramework.RAW_PYTHON)

    assert {agent.manifest.id for agent in raw_python_agents} == {"agent-alpha", "agent-gamma"}


def test_filter_by_scenario() -> None:
    registry = discover_agents(MIXED_OFFICIAL, MIXED_COMMUNITY)

    scenario_b_agents = registry.filter(scenario="scenario-b")

    assert {agent.manifest.id for agent in scenario_b_agents} == {"agent-beta", "agent-gamma"}


def test_filter_by_source() -> None:
    registry = discover_agents(MIXED_OFFICIAL, MIXED_COMMUNITY)

    official_agents = registry.filter(source=AgentSource.OFFICIAL)
    community_agents = registry.filter(source=AgentSource.COMMUNITY)

    assert {agent.manifest.id for agent in official_agents} == {"agent-alpha"}
    assert {agent.manifest.id for agent in community_agents} == {"agent-beta", "agent-gamma"}


def test_filter_combines_criteria() -> None:
    registry = discover_agents(MIXED_OFFICIAL, MIXED_COMMUNITY)

    agents = registry.filter(
        framework=AgentFramework.RAW_PYTHON,
        scenario="scenario-b",
        source=AgentSource.COMMUNITY,
    )

    assert {agent.manifest.id for agent in agents} == {"agent-gamma"}
