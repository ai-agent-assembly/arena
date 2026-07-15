"""Unit tests for match orchestration (`arena.runner.match`)."""

from __future__ import annotations

import json
import re
import shlex
import sys
from dataclasses import replace
from datetime import UTC, datetime
from pathlib import Path

import pytest

from arena.integrations.adapter import AdapterChoice
from arena.integrations.audit import REDACTION_MARKER, AuditEventStatus, read_audit_events
from arena.integrations.decision import DefenseDecision
from arena.models.scenario import Decision, Severity, TrialSpec
from arena.registry.discovery import discover_agents
from arena.runner.events import MatchEvent, MatchEventType
from arena.runner.llm_mode import LIVE_LLM_ENV_VAR, LLMMode
from arena.runner.match import (
    MatchConfig,
    MatchOrchestrationError,
    _trial_expectations_satisfied,
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


# --- MatchConfig.adapter ----------------------------------------------------


def test_match_config_defaults_to_fake_adapter(match_config: MatchConfig) -> None:
    # AAASM-4378: the fake/real adapter choice knob defaults to fake, since
    # no real agent-assembly connector exists yet — see
    # MatchConfig.adapter's docstring for how run_match consumes it.
    assert match_config.adapter is AdapterChoice.FAKE


def test_match_config_adapter_is_settable(tmp_path: Path) -> None:
    config = MatchConfig(output_root=tmp_path / "runs", adapter=AdapterChoice.REAL)

    assert config.adapter is AdapterChoice.REAL


# --- MatchConfig.llm_mode (AAASM-4405) --------------------------------------


def test_match_config_defaults_to_mock_llm_mode(match_config: MatchConfig) -> None:
    assert match_config.llm_mode is LLMMode.MOCK


def test_match_config_llm_mode_is_settable(tmp_path: Path) -> None:
    config = MatchConfig(output_root=tmp_path / "runs", llm_mode=LLMMode.REPLAY)

    assert config.llm_mode is LLMMode.REPLAY


def test_match_config_budget_guard_fields_default_to_none(tmp_path: Path) -> None:
    config = MatchConfig(output_root=tmp_path / "runs")

    assert config.max_live_calls is None
    assert config.max_cost_usd is None


def test_match_config_budget_guard_fields_are_settable(tmp_path: Path) -> None:
    config = MatchConfig(
        output_root=tmp_path / "runs",
        llm_mode=LLMMode.LIVE,
        max_live_calls=10,
        max_cost_usd=5.0,
    )

    assert config.max_live_calls == 10
    assert config.max_cost_usd == pytest.approx(5.0)


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


# --- run_match: llm_mode live-mode gating (AAASM-4405) ----------------------


def test_run_match_live_llm_mode_rejected_without_env_var(
    match_config: MatchConfig, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.delenv(LIVE_LLM_ENV_VAR, raising=False)
    live_config: MatchConfig = replace(match_config, llm_mode=LLMMode.LIVE)

    with pytest.raises(MatchOrchestrationError, match=LIVE_LLM_ENV_VAR):
        run_match("test-scenario", live_config)


def test_run_match_live_llm_mode_rejected_before_any_scenario_loading(
    match_config: MatchConfig, monkeypatch: pytest.MonkeyPatch
) -> None:
    # The live-mode gate runs before scenario loading, so an unknown
    # scenario id doesn't change the error a caller sees — live-mode
    # rejection is unconditional, not contingent on the rest of the match
    # setup succeeding.
    monkeypatch.delenv(LIVE_LLM_ENV_VAR, raising=False)
    live_config: MatchConfig = replace(match_config, llm_mode=LLMMode.LIVE)

    with pytest.raises(MatchOrchestrationError, match=LIVE_LLM_ENV_VAR):
        run_match("does-not-exist", live_config)


def test_run_match_live_llm_mode_allowed_with_env_var_set(
    match_config: MatchConfig, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv(LIVE_LLM_ENV_VAR, "true")
    live_config: MatchConfig = replace(match_config, llm_mode=LLMMode.LIVE)

    # Live mode is now permitted; the run proceeds to real match
    # orchestration (no official agent makes a real model call today, so
    # this exercises only the policy gate itself, not any live-call path).
    result = run_match("test-scenario", live_config)

    assert result.trial_outcomes


# --- run_match: MatchResult carries execution metadata (AAASM-4406) ---------


def test_run_match_result_carries_configured_llm_mode(match_config: MatchConfig) -> None:
    result = run_match("test-scenario", match_config)

    assert result.llm_mode is LLMMode.MOCK


def test_run_match_result_carries_configured_budget_guards(
    match_config: MatchConfig, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv(LIVE_LLM_ENV_VAR, "true")
    # Built via an explicit MatchConfig(...) call rather than
    # dataclasses.replace(...) — with three overridden fields at once,
    # replace()'s generic-TypeVar return type isn't resolved unambiguously
    # by every static analyzer, which was surfacing as a spurious
    # argument-type finding against run_match's `config: MatchConfig`
    # parameter even though the runtime value is a genuine MatchConfig.
    live_config = MatchConfig(
        scenarios_root=match_config.scenarios_root,
        official_root=match_config.official_root,
        community_root=match_config.community_root,
        output_root=match_config.output_root,
        llm_mode=LLMMode.LIVE,
        max_live_calls=7,
        max_cost_usd=2.5,
    )

    result = run_match("test-scenario", live_config)

    assert result.llm_mode is LLMMode.LIVE
    assert result.max_live_calls == 7
    assert result.max_cost_usd == pytest.approx(2.5)


# --- run_match: behavior_id cross-referential validation (AAASM-4404) --------


def test_run_match_unsupported_trial_behavior_id_raises(tmp_path: Path) -> None:
    scenarios_root = tmp_path / "scenarios"
    official_root = tmp_path / "agents" / "official"
    community_root = tmp_path / "agents" / "community"

    scenario_dir = scenarios_root / "behavior-scenario"
    trials_dir = scenario_dir / "trials"
    trials_dir.mkdir(parents=True)
    (scenario_dir / "scenario.yaml").write_text(
        "id: behavior-scenario\n"
        "name: Behavior Scenario\n"
        "description: Scenario used for behavior_id cross-referential tests.\n"
        "trials:\n"
        "  - behavior-trial\n"
    )
    (trials_dir / "behavior-trial.yaml").write_text(
        "id: behavior-trial\n"
        "description: A trial that targets a specific behavior profile.\n"
        "expected:\n"
        "  some.action: deny\n"
        "severity: high\n"
        "behavior_id: secret-seeking\n"
    )
    # This agent is compatible with the scenario but declares no behaviors
    # at all, so "secret-seeking" can never be satisfied.
    _write_agent(official_root, "agent-one", ["behavior-scenario"])

    config = MatchConfig(
        scenarios_root=scenarios_root,
        official_root=official_root,
        community_root=community_root,
        output_root=tmp_path / "runs",
    )

    with pytest.raises(MatchOrchestrationError, match="secret-seeking") as exc_info:
        run_match("behavior-scenario", config)

    message = str(exc_info.value)
    assert "behavior-trial" in message
    assert "agent-one" in message


def test_run_match_supported_trial_behavior_id_does_not_raise(tmp_path: Path) -> None:
    scenarios_root = tmp_path / "scenarios"
    official_root = tmp_path / "agents" / "official"
    community_root = tmp_path / "agents" / "community"

    scenario_dir = scenarios_root / "behavior-scenario"
    trials_dir = scenario_dir / "trials"
    trials_dir.mkdir(parents=True)
    (scenario_dir / "scenario.yaml").write_text(
        "id: behavior-scenario\n"
        "name: Behavior Scenario\n"
        "description: Scenario used for behavior_id cross-referential tests.\n"
        "trials:\n"
        "  - behavior-trial\n"
    )
    (trials_dir / "behavior-trial.yaml").write_text(
        "id: behavior-trial\n"
        "description: A trial that targets a specific behavior profile.\n"
        "expected:\n"
        "  some.action: deny\n"
        "severity: high\n"
        "behavior_id: secret-seeking\n"
    )
    agent_dir = official_root / "agent-one"
    agent_dir.mkdir(parents=True)
    (agent_dir / "agent.yaml").write_text(
        "id: agent-one\n"
        "name: Agent One\n"
        "framework: raw-python\n"
        'entrypoint:\n  type: command\n  command: "python main.py"\n'
        "runtime:\n"
        "  type: process\n"
        "scenarios:\n"
        "  - behavior-scenario\n"
        "behaviors:\n"
        "  - id: secret-seeking\n"
        "    description: Attempts to read a secrets file.\n"
    )

    config = MatchConfig(
        scenarios_root=scenarios_root,
        official_root=official_root,
        community_root=community_root,
        output_root=tmp_path / "runs",
    )

    # No MatchOrchestrationError: agent-one declares the "secret-seeking"
    # behavior the trial references, so run_match proceeds past the
    # behavior_id validation step (into the real — and here failing, since
    # "python main.py" doesn't exist — process launch, which is a separate
    # concern this test doesn't assert on).
    result = run_match("behavior-scenario", config)

    assert result.trial_outcomes[0].trial.behavior_id == "secret-seeking"


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


# --- real decision wiring / audit persistence (AAASM-4380) -------------------

#: A test-only agent that emits one `ArenaActionAttempt` per configured
#: action for whatever trial it's currently running, then exits 0. Uses
#: `sys.executable` plus an absolute script path (like
#: `tests/test_smoke_local_run.py`'s fixture) so it resolves correctly
#: regardless of where its trial workspace ends up.
_EMIT_AGENT_SCRIPT_TEMPLATE = '''\
"""Test-only agent: emits one ArenaActionAttempt per configured action for
its current trial, then exits 0."""
import os

from arena.integrations.emit import emit_action_attempt

_ACTIONS_BY_TRIAL = {actions_json}

trial_id = os.environ.get("ARENA_TRIAL_ID", "")
for tool, resource, args in _ACTIONS_BY_TRIAL.get(trial_id, []):
    emit_action_attempt(
        tool=tool,
        resource=resource,
        framework="raw-python",
        scenario_id={scenario_id!r},
        args=args,
    )
'''


def _write_emitting_agent(
    official_root: Path,
    agent_id: str,
    scenario_id: str,
    scenario_ids: list[str],
    actions_by_trial: dict[str, list[tuple[str, str, dict[str, str]]]],
) -> None:
    agent_dir = official_root / agent_id
    agent_dir.mkdir(parents=True)
    script_path = agent_dir / "main.py"
    script_path.write_text(
        _EMIT_AGENT_SCRIPT_TEMPLATE.format(
            actions_json=json.dumps(actions_by_trial), scenario_id=scenario_id
        )
    )
    command = f"{shlex.quote(sys.executable)} {shlex.quote(str(script_path))}"
    scenarios_yaml = "\n".join(f"  - {sid}" for sid in scenario_ids)
    (agent_dir / "agent.yaml").write_text(
        f"id: {agent_id}\n"
        f"name: {agent_id.title()}\n"
        f"framework: raw-python\n"
        f"entrypoint:\n"
        f"  type: command\n"
        f'  command: "{command}"\n'
        f"runtime:\n"
        f"  type: process\n"
        f"scenarios:\n{scenarios_yaml}\n"
    )


def _write_custom_scenario(
    root: Path,
    scenario_id: str,
    trial_id: str,
    expected: dict[str, str],
    severity: str = "high",
) -> None:
    scenario_dir = root / scenario_id
    trials_dir = scenario_dir / "trials"
    trials_dir.mkdir(parents=True)
    (scenario_dir / "scenario.yaml").write_text(
        f"id: {scenario_id}\n"
        f"name: Test Scenario\n"
        f"description: Scenario used for audit/decision wiring tests.\n"
        f"trials:\n"
        f"  - {trial_id}\n"
    )
    expected_yaml = "\n".join(f"  {action}: {decision}" for action, decision in expected.items())
    (trials_dir / f"{trial_id}.yaml").write_text(
        f"id: {trial_id}\n"
        f"description: A trial used for audit/decision wiring tests.\n"
        f"expected:\n{expected_yaml}\n"
        f"severity: {severity}\n"
    )


def test_run_match_writes_audit_jsonl_covering_every_decision_type(tmp_path: Path) -> None:
    scenarios_root = tmp_path / "scenarios"
    official_root = tmp_path / "agents" / "official"
    community_root = tmp_path / "agents" / "community"

    expected = {
        "action.allow": "allow",
        "action.deny": "deny",
        "action.ask": "ask",
        "action.redact": "redact",
        "action.drop": "drop",
        "action.quarantine": "quarantine",
    }
    _write_custom_scenario(
        scenarios_root, "all-decisions-scenario", "all-decisions-trial", expected
    )
    actions: dict[str, list[tuple[str, str, dict[str, str]]]] = {
        "all-decisions-trial": [(action, "some/resource", {}) for action in expected]
    }
    _write_emitting_agent(
        official_root, "emit-agent", "all-decisions-scenario", ["all-decisions-scenario"], actions
    )

    config = MatchConfig(
        scenarios_root=scenarios_root,
        official_root=official_root,
        community_root=community_root,
        output_root=tmp_path / "runs",
    )
    result = run_match("all-decisions-scenario", config)

    events = read_audit_events(result.workspace / "audit.jsonl")
    assert len(events) == len(expected)
    assert {event.status for event in events} == {AuditEventStatus.DECIDED}
    actual_effects = {
        event.attempt.tool: event.decision.effect.value
        for event in events
        if event.attempt is not None and event.decision is not None
    }
    assert actual_effects == expected

    assert result.trial_outcomes[0].passed is True


def test_run_match_missing_decision_does_not_crash_and_fails_trial(tmp_path: Path) -> None:
    scenarios_root = tmp_path / "scenarios"
    official_root = tmp_path / "agents" / "official"
    community_root = tmp_path / "agents" / "community"

    _write_custom_scenario(
        scenarios_root,
        "missing-decision-scenario",
        "missing-decision-trial",
        {"known.action": "allow"},
    )
    actions: dict[str, list[tuple[str, str, dict[str, str]]]] = {
        "missing-decision-trial": [
            ("known.action", "some/resource", {}),
            ("unlisted.action", "some/resource", {}),
        ]
    }
    _write_emitting_agent(
        official_root,
        "emit-agent",
        "missing-decision-scenario",
        ["missing-decision-scenario"],
        actions,
    )

    config = MatchConfig(
        scenarios_root=scenarios_root,
        official_root=official_root,
        community_root=community_root,
        output_root=tmp_path / "runs",
    )
    # A MissingDecisionError for the unlisted action must not crash the
    # match — it's recorded as a reportable failure, not an exception.
    result = run_match("missing-decision-scenario", config)

    outcome = result.trial_outcomes[0]
    assert outcome.error is None
    assert outcome.passed is False

    events = read_audit_events(result.workspace / "audit.jsonl")
    statuses = {event.attempt.tool: event.status for event in events if event.attempt is not None}
    assert statuses["known.action"] is AuditEventStatus.DECIDED
    assert statuses["unlisted.action"] is AuditEventStatus.MISSING_DECISION


def test_run_match_passed_is_decision_based_not_exit_code_based(tmp_path: Path) -> None:
    scenarios_root = tmp_path / "scenarios"
    official_root = tmp_path / "agents" / "official"
    community_root = tmp_path / "agents" / "community"

    _write_custom_scenario(
        scenarios_root, "decision-based-scenario", "decision-based-trial", {"some.action": "allow"}
    )
    # This agent exits 0 without ever attempting "some.action". Under the
    # old exit_code == 0 proxy this trial would have shown PASS; under real
    # decision-based scoring it must FAIL — the trial's one expected action
    # was never attempted, so there's no decision evidence for it at all.
    _write_emitting_agent(
        official_root, "silent-agent", "decision-based-scenario", ["decision-based-scenario"], {}
    )

    config = MatchConfig(
        scenarios_root=scenarios_root,
        official_root=official_root,
        community_root=community_root,
        output_root=tmp_path / "runs",
    )
    result = run_match("decision-based-scenario", config)

    outcome = result.trial_outcomes[0]
    assert outcome.result.exit_code == 0
    assert outcome.passed is False


def test_run_match_redacts_persisted_args_for_redact_decision(tmp_path: Path) -> None:
    scenarios_root = tmp_path / "scenarios"
    official_root = tmp_path / "agents" / "official"
    community_root = tmp_path / "agents" / "community"

    _write_custom_scenario(
        scenarios_root, "redact-scenario", "redact-trial", {"log.write": "redact"}
    )
    actions = {"redact-trial": [("log.write", "logs/output.txt", {"body": "sk-fake-secret-value"})]}
    _write_emitting_agent(
        official_root, "emit-agent", "redact-scenario", ["redact-scenario"], actions
    )

    config = MatchConfig(
        scenarios_root=scenarios_root,
        official_root=official_root,
        community_root=community_root,
        output_root=tmp_path / "runs",
    )
    result = run_match("redact-scenario", config)

    assert result.trial_outcomes[0].passed is True

    raw_lines = (result.workspace / "audit.jsonl").read_text(encoding="utf-8").splitlines()
    assert len(raw_lines) == 1
    payload = json.loads(raw_lines[0])
    assert payload["attempt"]["args"] == {"body": REDACTION_MARKER}


# --- agent-role-aware expected coverage (AAASM-4408) -------------------------
#
# AAASM-4408's fix: `trial.expected` no longer requires a single agent to
# have attempted *every* key. `_trial_expectations_satisfied` is the
# extracted, directly-testable function `TrialOutcome.passed` delegates to
# (see its own docstring in `arena.runner.match`); these tests exercise it
# directly, including with hand-built `DefenseDecision`s a live
# `FakeAgentAssemblyClient` (whose decisions are always copied straight from
# `trial.expected`) could never actually produce — that's the only way to
# reach the "attempted but wrong decision" branch at all, which is what
# proves the fix didn't also weaken AAASM-4380's fail-closed guarantee.


def _decision(effect: Decision) -> DefenseDecision:
    return DefenseDecision(
        effect=effect, layer="policy", reason="test decision", severity=Severity.LOW
    )


def _trial(expected: dict[str, Decision], agent_roles: list[str] | None = None) -> TrialSpec:
    return TrialSpec(
        id="role-aware-trial",
        description="A trial used for AAASM-4408 pass/fail semantics tests.",
        agent_roles=agent_roles or [],
        expected=expected,
        severity=Severity.HIGH,
    )


def test_trial_expectations_satisfied_true_for_full_coverage() -> None:
    # The pre-AAASM-4408 case still works: every expected key attempted and
    # matched.
    trial = _trial({"tool.a": Decision.ALLOW, "tool.b": Decision.DENY})
    decisions = {"tool.a": _decision(Decision.ALLOW), "tool.b": _decision(Decision.DENY)}

    assert _trial_expectations_satisfied(trial, decisions) is True


def test_trial_expectations_satisfied_true_for_partial_role_specific_coverage() -> None:
    # This is AAASM-4408's actual fix: two different agent roles each only
    # attempt their own slice of a multi-key `expected` map (e.g.
    # `docs.write` for a docs agent vs. `github.issues.comment` for an
    # issue triager on the same trial) — neither needs to touch the other's
    # unrelated key to pass.
    trial = _trial(
        {"docs.write": Decision.ALLOW, "github.issues.comment": Decision.ALLOW},
        agent_roles=["issue_triager", "docs_maintainer"],
    )

    docs_agent_decisions = {"docs.write": _decision(Decision.ALLOW)}
    triager_decisions = {"github.issues.comment": _decision(Decision.ALLOW)}

    assert _trial_expectations_satisfied(trial, docs_agent_decisions) is True
    assert _trial_expectations_satisfied(trial, triager_decisions) is True


def test_trial_expectations_satisfied_false_when_no_decisions_at_all() -> None:
    # Non-vacuous guard: an agent process that emitted nothing does not get
    # to pass a trial it never touched.
    trial = _trial({"tool.a": Decision.ALLOW})

    assert _trial_expectations_satisfied(trial, {}) is False


def test_trial_expectations_satisfied_false_when_only_irrelevant_tools_attempted() -> None:
    # Non-vacuous guard also applies when the agent attempted something, but
    # nothing that trial.expected actually covers — e.g. an agent whose
    # role has no legitimate reason to act on this trial at all (mirrors
    # mock-malicious-agent emitting nothing for issue-triage-happy-path
    # live — see the AAASM-4408 PR description's trial-outcome table).
    trial = _trial({"tool.a": Decision.ALLOW})
    decisions = {"unrelated.tool": _decision(Decision.ALLOW)}

    assert _trial_expectations_satisfied(trial, decisions) is False


def test_trial_expectations_satisfied_false_when_attempted_action_decision_is_wrong() -> None:
    # Regression test for the fail-closed guarantee AAASM-4408 must not
    # weaken: an agent's own attempted, trial.expected-covered action
    # receiving the *wrong* decision (e.g. an `allow` where `deny` was
    # expected — the shape of langgraph-docs-agent's `fs.write` on
    # prompt-injection-code-write, had agent-assembly's governance actually
    # let it through) still fails the trial, regardless of how many other
    # keys the agent skipped or got right.
    trial = _trial({"fs.write": Decision.DENY, "docs.write": Decision.ALLOW})
    decisions = {
        "fs.write": _decision(Decision.ALLOW),  # wrong: should have been denied
        "docs.write": _decision(Decision.ALLOW),  # this one is correct
    }

    assert _trial_expectations_satisfied(trial, decisions) is False


def test_trial_expectations_satisfied_ignores_keys_outside_expected() -> None:
    # Forward-compat with a future non-FAKE adapter: a decision for a tool
    # with no trial.expected entry at all doesn't factor into this
    # function's verdict either way (run_match's own MissingDecisionError /
    # audit_failure handling is what fails that case, separately).
    trial = _trial({"tool.a": Decision.ALLOW})
    decisions = {
        "tool.a": _decision(Decision.ALLOW),
        "tool.outside.expected": _decision(Decision.DENY),
    }

    assert _trial_expectations_satisfied(trial, decisions) is True


def test_run_match_two_agents_each_cover_only_their_own_expected_slice(tmp_path: Path) -> None:
    """Orchestration-level counterpart to the unit tests above: two
    `run_match`-launched agents, each attempting only one of a two-key
    trial, both pass — reproducing AAASM-4408's actual motivating gap
    (raw-python-issue-triager and langgraph-docs-agent both failing
    `issue-triage-happy-path` under the old all-keys-required semantics)
    and proving it's fixed via the real orchestration path, not just the
    extracted helper.
    """
    scenarios_root = tmp_path / "scenarios"
    official_root = tmp_path / "agents" / "official"
    community_root = tmp_path / "agents" / "community"

    _write_custom_scenario(
        scenarios_root,
        "role-aware-scenario",
        "role-aware-trial",
        {"docs.write": "allow", "github.issues.comment": "allow"},
    )
    _write_emitting_agent(
        official_root,
        "docs-agent",
        "role-aware-scenario",
        ["role-aware-scenario"],
        {"role-aware-trial": [("docs.write", "docs/usage.md", {})]},
    )
    _write_emitting_agent(
        official_root,
        "triager-agent",
        "role-aware-scenario",
        ["role-aware-scenario"],
        {"role-aware-trial": [("github.issues.comment", "issues/1", {})]},
    )

    config = MatchConfig(
        scenarios_root=scenarios_root,
        official_root=official_root,
        community_root=community_root,
        output_root=tmp_path / "runs",
    )
    result = run_match("role-aware-scenario", config)

    outcomes_by_agent = {outcome.agent_id: outcome for outcome in result.trial_outcomes}
    assert outcomes_by_agent["docs-agent"].passed is True
    assert outcomes_by_agent["triager-agent"].passed is True
