"""Unit tests for match orchestration (`arena.runner.match`)."""

from __future__ import annotations

import re
from datetime import UTC, datetime
from pathlib import Path

import pytest

from arena.registry.discovery import discover_agents
from arena.runner.events import MatchEvent, MatchEventType
from arena.runner.match import (
    MatchConfig,
    MatchOrchestrationError,
    generate_match_id,
    run_match,
    select_agents,
)

FIXTURES_DIR = Path(__file__).parent / "fixtures" / "registry"
MIXED_OFFICIAL = FIXTURES_DIR / "mixed" / "official"
MIXED_COMMUNITY = FIXTURES_DIR / "mixed" / "community"

_FIXED_NOW = datetime(2026, 7, 10, 12, 0, 0, tzinfo=UTC)


def _write_scenario(root: Path, scenario_id: str = "test-scenario") -> None:
    scenario_dir = root / scenario_id
    trials_dir = scenario_dir / "trials"
    trials_dir.mkdir(parents=True)
    (scenario_dir / "scenario.yaml").write_text(
        f"id: {scenario_id}\n"
        f"name: Test Scenario\n"
        f"description: Scenario used for match orchestration tests.\n"
        f"victory_conditions:\n"
        f"  critical_escapes: 0\n"
        f"trials:\n"
        f"  - happy-trial\n"
        f"  - critical-trial\n"
    )
    (trials_dir / "happy-trial.yaml").write_text(
        "id: happy-trial\n"
        "description: A benign trial.\n"
        "expected:\n"
        "  some.action: allow\n"
        "severity: low\n"
    )
    (trials_dir / "critical-trial.yaml").write_text(
        "id: critical-trial\n"
        "description: A critical trial.\n"
        "expected:\n"
        "  some.action: deny\n"
        "severity: critical\n"
    )


def _write_agent(root: Path, agent_id: str, scenario_ids: list[str]) -> None:
    agent_dir = root / agent_id
    agent_dir.mkdir(parents=True)
    scenarios_yaml = "\n".join(f"  - {sid}" for sid in scenario_ids)
    (agent_dir / "agent.yaml").write_text(
        f"id: {agent_id}\n"
        f"name: {agent_id.title()}\n"
        f"framework: raw-python\n"
        f"entrypoint:\n"
        f'  type: command\n  command: "python main.py"\n'
        f"runtime:\n"
        f"  type: process\n"
        f"scenarios:\n{scenarios_yaml}\n"
    )


@pytest.fixture
def match_config(tmp_path: Path) -> MatchConfig:
    scenarios_root = tmp_path / "scenarios"
    official_root = tmp_path / "agents" / "official"
    community_root = tmp_path / "agents" / "community"

    _write_scenario(scenarios_root)
    _write_agent(official_root, "agent-one", ["test-scenario"])
    _write_agent(community_root, "agent-two", ["test-scenario"])
    _write_agent(community_root, "agent-other", ["other-scenario"])

    return MatchConfig(
        scenarios_root=scenarios_root,
        official_root=official_root,
        community_root=community_root,
        output_root=tmp_path / "runs",
    )


# --- generate_match_id ------------------------------------------------------


def test_generate_match_id_format() -> None:
    match_id = generate_match_id("test-scenario", now=_FIXED_NOW, unique="deadbeef")

    assert match_id == "20260710T120000Z-test-scenario-deadbeef"


def test_generate_match_id_is_stable_given_fixed_inputs() -> None:
    first = generate_match_id("test-scenario", now=_FIXED_NOW, unique="deadbeef")
    second = generate_match_id("test-scenario", now=_FIXED_NOW, unique="deadbeef")

    assert first == second


def test_generate_match_id_is_unique_by_default() -> None:
    first = generate_match_id("test-scenario", now=_FIXED_NOW)
    second = generate_match_id("test-scenario", now=_FIXED_NOW)

    assert first != second
    assert re.fullmatch(r"20260710T120000Z-test-scenario-[0-9a-f]{8}", first)
    assert re.fullmatch(r"20260710T120000Z-test-scenario-[0-9a-f]{8}", second)


# --- select_agents -----------------------------------------------------------


def test_select_agents_filters_by_scenario_compatibility() -> None:
    registry = discover_agents(MIXED_OFFICIAL, MIXED_COMMUNITY)

    selected = select_agents(registry, "scenario-b", agent_id=None)

    assert [a.manifest.id for a in selected] == ["agent-beta", "agent-gamma"]


def test_select_agents_filters_by_agent_id() -> None:
    registry = discover_agents(MIXED_OFFICIAL, MIXED_COMMUNITY)

    selected = select_agents(registry, "scenario-b", agent_id="agent-gamma")

    assert [a.manifest.id for a in selected] == ["agent-gamma"]


def test_select_agents_unknown_agent_id_raises() -> None:
    registry = discover_agents(MIXED_OFFICIAL, MIXED_COMMUNITY)

    with pytest.raises(MatchOrchestrationError, match="agent-zulu"):
        select_agents(registry, "scenario-b", agent_id="agent-zulu")


def test_select_agents_incompatible_agent_id_raises() -> None:
    registry = discover_agents(MIXED_OFFICIAL, MIXED_COMMUNITY)

    with pytest.raises(MatchOrchestrationError, match="agent-alpha"):
        select_agents(registry, "scenario-b", agent_id="agent-alpha")


# --- run_match: errors --------------------------------------------------------


def test_run_match_unknown_scenario_raises(match_config: MatchConfig) -> None:
    with pytest.raises(MatchOrchestrationError, match="not found"):
        run_match("does-not-exist", match_config)


def test_run_match_no_compatible_agents_raises(match_config: MatchConfig, tmp_path: Path) -> None:
    _write_scenario(match_config.scenarios_root, "lonely-scenario")

    with pytest.raises(MatchOrchestrationError, match="no registered agents"):
        run_match("lonely-scenario", match_config)


# --- run_match: happy path ----------------------------------------------------


def test_run_match_selects_only_compatible_agents(match_config: MatchConfig) -> None:
    result = run_match("test-scenario", match_config, now=_FIXED_NOW)

    agent_ids = {outcome.agent_id for outcome in result.trial_outcomes}
    assert agent_ids == {"agent-one", "agent-two"}


def test_run_match_agent_filter_runs_only_that_agent(match_config: MatchConfig) -> None:
    result = run_match("test-scenario", match_config, agent_id="agent-one", now=_FIXED_NOW)

    agent_ids = {outcome.agent_id for outcome in result.trial_outcomes}
    assert agent_ids == {"agent-one"}


def test_run_match_creates_match_and_trial_workspaces(match_config: MatchConfig) -> None:
    result = run_match("test-scenario", match_config, agent_id="agent-one", now=_FIXED_NOW)

    assert result.workspace.is_dir()
    assert (result.workspace / "agent-one" / "happy-trial").is_dir()
    assert (result.workspace / "agent-one" / "critical-trial").is_dir()


def test_run_match_with_failing_command_reports_without_crashing(
    match_config: MatchConfig,
) -> None:
    # AAASM-4374 wired ProcessRunner in as the default COMMAND runner, so
    # this fixture's "python main.py" (no such file exists under the fixture
    # agent dirs) now really launches and really fails — every trial for
    # every agent gets a non-zero synthetic exit code from ProcessRunner
    # instead of NoOpRunner's unconditional success. That's exactly the
    # behavior this test now exercises: a failing agent process is reported
    # as a lost trial/critical escape, not a crash of run_match itself (see
    # AAASM-4372's "failed agent process does not crash the whole runner"
    # acceptance criterion, and `Runner.run`'s docstring).
    result = run_match("test-scenario", match_config, now=_FIXED_NOW)

    assert result.critical_escapes == 2  # one critical-trial per agent
    assert result.victory_conditions_violated is True
    assert all(not outcome.passed for outcome in result.trial_outcomes)
    assert all(outcome.error is None for outcome in result.trial_outcomes)
    assert all(outcome.result.exit_code != 0 for outcome in result.trial_outcomes)


def test_run_match_event_sequence_is_ordered_and_deterministic(
    match_config: MatchConfig,
) -> None:
    result = run_match("test-scenario", match_config, agent_id="agent-one", now=_FIXED_NOW)

    # agent-one x [happy-trial, critical-trial], bracketed by match start/finish.
    expected_types = [
        MatchEventType.MATCH_STARTED,
        MatchEventType.TRIAL_STARTED,
        MatchEventType.AGENT_STARTED,
        MatchEventType.AGENT_FINISHED,
        MatchEventType.TRIAL_FINISHED,
        MatchEventType.TRIAL_STARTED,
        MatchEventType.AGENT_STARTED,
        MatchEventType.AGENT_FINISHED,
        MatchEventType.TRIAL_FINISHED,
        MatchEventType.MATCH_FINISHED,
    ]
    assert [event.type for event in result.events] == expected_types

    expected_trial_ids = [
        None,
        "happy-trial",
        "happy-trial",
        "happy-trial",
        "happy-trial",
        "critical-trial",
        "critical-trial",
        "critical-trial",
        "critical-trial",
        None,
    ]
    assert [event.trial_id for event in result.events] == expected_trial_ids
    assert all(event.match_id == result.match_id for event in result.events)


def test_run_match_two_agents_iterates_agent_outer_trial_inner(
    match_config: MatchConfig,
) -> None:
    result = run_match("test-scenario", match_config, now=_FIXED_NOW)

    agent_trial_pairs = [
        (event.agent_id, event.trial_id)
        for event in result.events
        if event.type is MatchEventType.TRIAL_STARTED
    ]
    assert agent_trial_pairs == [
        ("agent-one", "happy-trial"),
        ("agent-one", "critical-trial"),
        ("agent-two", "happy-trial"),
        ("agent-two", "critical-trial"),
    ]


def test_run_match_is_deterministic_across_independent_runs(match_config: MatchConfig) -> None:
    first = run_match("test-scenario", match_config, now=_FIXED_NOW)
    second = run_match("test-scenario", match_config, now=_FIXED_NOW)

    def shape(
        events: tuple[MatchEvent, ...],
    ) -> list[tuple[MatchEventType, str | None, str | None]]:
        return [(e.type, e.agent_id, e.trial_id) for e in events]

    assert shape(first.events) == shape(second.events)
    assert first.critical_escapes == second.critical_escapes
    assert first.victory_conditions_violated == second.victory_conditions_violated
    # match ids are still unique per run even with the same `now`.
    assert first.match_id != second.match_id
