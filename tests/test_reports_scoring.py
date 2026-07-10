"""Unit tests for `arena.reports.scoring.score_match` (AAASM-4389).

Builds `MatchResult`/`ArenaAuditEvent` fixtures by hand rather than through
a full `run_match` — the same pattern `test_runner_match.py`'s
`_trial_expectations_satisfied` tests and `test_integrations_audit.py` use
— since `score_match` only reads `MatchResult`/`ScenarioSpec`/
`ArenaAuditEvent` shapes, not anything a real agent process produces.
`AdapterChoice.FAKE`'s decisions always mirror `TrialSpec.expected` exactly
(see `FakeAgentAssemblyClient.from_trial_spec`), so a live match can never
actually produce an unexpected-allow/secret-exposure/approval-bypass audit
event — these categories are only exercisable via hand-built events like
the ones below.
"""

from __future__ import annotations

from pathlib import Path

from arena.integrations.audit import ArenaAuditEvent
from arena.integrations.decision import DefenseDecision
from arena.integrations.models import ArenaActionAttempt
from arena.models.scenario import Decision, ScenarioSpec, Severity, TrialSpec, VictoryConditions
from arena.reports.scoring import MatchOutcome, score_match
from arena.runner.base import AgentRunResult
from arena.runner.match import MatchResult, TrialOutcome

_MATCH_ID = "20260710T000000Z-test-scenario-deadbeef"


def _trial(
    *,
    id: str = "some-trial",
    expected: dict[str, Decision],
    severity: Severity = Severity.LOW,
) -> TrialSpec:
    return TrialSpec(
        id=id,
        description="A trial used for scoring tests.",
        expected=expected,
        severity=severity,
    )


def _scenario(
    *,
    trial_ids: list[str],
    victory_conditions: VictoryConditions | None = None,
) -> ScenarioSpec:
    return ScenarioSpec(
        id="test-scenario",
        name="Test Scenario",
        description="Scenario used for scoring tests.",
        victory_conditions=victory_conditions or VictoryConditions(),
        trials=trial_ids,
    )


def _run_result(*, exit_code: int = 0) -> AgentRunResult:
    return AgentRunResult(exit_code=exit_code, stdout="", stderr="", duration_seconds=0.1)


def _outcome(
    *, trial: TrialSpec, agent_id: str = "agent-a", passed: bool, error: str | None = None
) -> TrialOutcome:
    return TrialOutcome(
        trial=trial,
        agent_id=agent_id,
        result=_run_result(exit_code=0 if error is None else 1),
        passed=passed,
        error=error,
    )


def _match_result(
    *, scenario: ScenarioSpec, trial_outcomes: list[TrialOutcome], critical_escapes: int
) -> MatchResult:
    return MatchResult(
        match_id=_MATCH_ID,
        scenario=scenario,
        workspace=Path("/unused"),
        events=(),
        trial_outcomes=tuple(trial_outcomes),
        critical_escapes=critical_escapes,
        victory_conditions_violated=critical_escapes > scenario.victory_conditions.critical_escapes,
    )


def _attempt(*, trial_id: str, tool: str, resource: str = "some/resource") -> ArenaActionAttempt:
    return ArenaActionAttempt(
        agent_id="agent-a",
        framework="raw-python",
        scenario_id="test-scenario",
        trial_id=trial_id,
        tool=tool,
        resource=resource,
    )


def _decided_event(
    *, trial_id: str, tool: str, effect: Decision, resource: str = "some/resource"
) -> ArenaAuditEvent:
    attempt = _attempt(trial_id=trial_id, tool=tool, resource=resource)
    decision = DefenseDecision(
        effect=effect, layer="policy", reason="canned test decision", severity=Severity.LOW
    )
    return ArenaAuditEvent.for_decision(match_id=_MATCH_ID, attempt=attempt, decision=decision)


def _missing_decision_event(*, trial_id: str, tool: str) -> ArenaAuditEvent:
    attempt = _attempt(trial_id=trial_id, tool=tool)
    return ArenaAuditEvent.for_missing_decision(
        match_id=_MATCH_ID, attempt=attempt, severity=Severity.LOW, error="no configured decision"
    )


# --- winning match ------------------------------------------------------------


def test_score_match_winning_match_has_zero_counts_and_wins() -> None:
    trial = _trial(
        id="happy-trial", expected={"some.action": Decision.ALLOW}, severity=Severity.LOW
    )
    scenario = _scenario(trial_ids=[trial.id])
    match_result = _match_result(
        scenario=scenario,
        trial_outcomes=[_outcome(trial=trial, passed=True)],
        critical_escapes=0,
    )
    audit_events = [_decided_event(trial_id=trial.id, tool="some.action", effect=Decision.ALLOW)]

    score = score_match(match_result, scenario, audit_events)

    assert score.critical_escapes == 0
    assert score.unexpected_allows == 0
    assert score.secret_exposures == 0
    assert score.approval_bypasses == 0
    assert score.missing_audits == 0
    assert score.agent_runtime_failures == 0
    assert score.outcome is MatchOutcome.AGENT_ASSEMBLY_WINS
    assert score.victory is True
    assert score.match_id == _MATCH_ID
