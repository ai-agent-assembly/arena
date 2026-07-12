"""Unit tests for `arena.reports.generate` (AAASM-4390): writing
`arena-report.md`, `arena-report.json`, and `audit.jsonl` under
`<reports_root>/<match-id>/`.

Builds `MatchResult`/`ArenaAuditEvent` fixtures by hand rather than through a
full `run_match`, mirroring `test_reports_scoring.py`'s own pattern — this
module only needs `MatchResult`/`ScenarioSpec`/`ArenaAuditEvent` shapes, not
anything a real agent process produces.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path

from arena.integrations.audit import ArenaAuditEvent
from arena.integrations.decision import DefenseDecision
from arena.integrations.models import ArenaActionAttempt
from arena.models.scenario import Decision, ScenarioSpec, Severity, TrialSpec, VictoryConditions
from arena.reports.generate import (
    ARENA_REPORT_JSON_FILENAME,
    ARENA_REPORT_MD_FILENAME,
    build_execution_metadata,
    build_report,
    generate_report,
)
from arena.reports.models import SCHEMA_VERSION, MatchReport
from arena.reports.scoring import MatchOutcome, score_match
from arena.runner.base import AgentRunResult
from arena.runner.events import MatchEvent, MatchEventType
from arena.runner.llm_mode import LLMMode
from arena.runner.match import AUDIT_LOG_FILENAME, MatchResult, TrialOutcome

_MATCH_ID = "20260710T000000Z-test-scenario-deadbeef"
_MATCH_STARTED_AT = datetime(2026, 7, 10, 0, 0, 0, tzinfo=UTC)


def _trial(
    *,
    id: str = "some-trial",
    expected: dict[str, Decision] | None = None,
    severity: Severity = Severity.LOW,
    behavior_id: str | None = None,
) -> TrialSpec:
    return TrialSpec(
        id=id,
        description="A trial used for report generation tests.",
        expected=expected or {"some.action": Decision.ALLOW},
        severity=severity,
        behavior_id=behavior_id,
    )


def _scenario(*, trial_ids: list[str]) -> ScenarioSpec:
    return ScenarioSpec(
        id="test-scenario",
        name="Test Scenario",
        description="Scenario used for report generation tests.",
        victory_conditions=VictoryConditions(),
        trials=trial_ids,
    )


def _run_result(*, exit_code: int = 0) -> AgentRunResult:
    return AgentRunResult(exit_code=exit_code, stdout="", stderr="", duration_seconds=1.5)


def _outcome(
    *, trial: TrialSpec, agent_id: str = "agent-a", passed: bool = True, error: str | None = None
) -> TrialOutcome:
    return TrialOutcome(
        trial=trial,
        agent_id=agent_id,
        result=_run_result(exit_code=0 if error is None else 1),
        passed=passed,
        error=error,
    )


def _attempt(
    *, trial_id: str, tool: str, agent_id: str = "agent-a", resource: str = "some/resource"
) -> ArenaActionAttempt:
    return ArenaActionAttempt(
        agent_id=agent_id,
        framework="raw-python",
        scenario_id="test-scenario",
        trial_id=trial_id,
        tool=tool,
        resource=resource,
    )


def _decided_event(
    *,
    trial_id: str,
    tool: str,
    effect: Decision = Decision.ALLOW,
    agent_id: str = "agent-a",
) -> ArenaAuditEvent:
    attempt = _attempt(trial_id=trial_id, tool=tool, agent_id=agent_id)
    decision = DefenseDecision(
        effect=effect, layer="policy", reason="canned test decision", severity=Severity.LOW
    )
    return ArenaAuditEvent.for_decision(match_id=_MATCH_ID, attempt=attempt, decision=decision)


def _match_result(
    *,
    scenario: ScenarioSpec,
    trial_outcomes: list[TrialOutcome],
    workspace: Path,
    llm_mode: LLMMode = LLMMode.MOCK,
    max_live_calls: int | None = None,
    max_cost_usd: float | None = None,
) -> MatchResult:
    return MatchResult(
        match_id=_MATCH_ID,
        scenario=scenario,
        workspace=workspace,
        events=(
            MatchEvent(
                type=MatchEventType.MATCH_STARTED,
                match_id=_MATCH_ID,
                timestamp=_MATCH_STARTED_AT,
                scenario_id=scenario.id,
            ),
        ),
        trial_outcomes=tuple(trial_outcomes),
        critical_escapes=0,
        victory_conditions_violated=False,
        llm_mode=llm_mode,
        max_live_calls=max_live_calls,
        max_cost_usd=max_cost_usd,
    )


def _standard_match(workspace: Path) -> tuple[MatchResult, list[ArenaAuditEvent]]:
    trial = _trial(id="happy-trial", expected={"some.action": Decision.ALLOW})
    scenario = _scenario(trial_ids=[trial.id])
    match_result = _match_result(
        scenario=scenario, trial_outcomes=[_outcome(trial=trial)], workspace=workspace
    )
    audit_events = [_decided_event(trial_id=trial.id, tool="some.action")]
    return match_result, audit_events


# --- generate_report: file placement -----------------------------------------


def test_generate_report_writes_all_three_files_under_reports_root(tmp_path: Path) -> None:
    match_result, audit_events = _standard_match(tmp_path / "runs" / _MATCH_ID)
    score = score_match(match_result, match_result.scenario, audit_events)
    reports_root = tmp_path / "reports" / "matches"

    report_dir = generate_report(match_result, score, audit_events, reports_root=reports_root)

    assert report_dir == reports_root / _MATCH_ID
    assert (report_dir / ARENA_REPORT_MD_FILENAME).is_file()
    assert (report_dir / ARENA_REPORT_JSON_FILENAME).is_file()
    assert (report_dir / AUDIT_LOG_FILENAME).is_file()


def test_generate_report_creates_reports_root_if_missing(tmp_path: Path) -> None:
    match_result, audit_events = _standard_match(tmp_path / "runs" / _MATCH_ID)
    score = score_match(match_result, match_result.scenario, audit_events)
    reports_root = tmp_path / "does" / "not" / "exist" / "yet"

    report_dir = generate_report(match_result, score, audit_events, reports_root=reports_root)

    assert report_dir.is_dir()


# --- Markdown content ----------------------------------------------------------


def test_generate_report_markdown_contains_summary_and_trial_sections(tmp_path: Path) -> None:
    match_result, audit_events = _standard_match(tmp_path / "runs" / _MATCH_ID)
    score = score_match(match_result, match_result.scenario, audit_events)
    reports_root = tmp_path / "reports"

    report_dir = generate_report(match_result, score, audit_events, reports_root=reports_root)
    markdown = (report_dir / ARENA_REPORT_MD_FILENAME).read_text(encoding="utf-8")

    assert f"# Arena Match Report: `{_MATCH_ID}`" in markdown
    assert "## Summary" in markdown
    assert "agent-assembly wins" in markdown
    assert "## Trials" in markdown
    assert "`happy-trial` — agent-a — PASS" in markdown
    assert "some.action" in markdown
    assert "## Execution" in markdown
    assert "`mock`" in markdown
    assert "- **Behavior profile:** (default)" in markdown


def test_generate_report_markdown_shows_failed_trial_and_error(tmp_path: Path) -> None:
    trial = _trial(id="broken-trial", expected={"some.action": Decision.ALLOW})
    scenario = _scenario(trial_ids=[trial.id])
    workspace = tmp_path / "runs" / _MATCH_ID
    match_result = _match_result(
        scenario=scenario,
        trial_outcomes=[_outcome(trial=trial, passed=False, error="agent crashed")],
        workspace=workspace,
    )
    audit_events: list[ArenaAuditEvent] = []
    score = score_match(match_result, scenario, audit_events)

    report_dir = generate_report(
        match_result, score, audit_events, reports_root=tmp_path / "reports"
    )
    markdown = (report_dir / ARENA_REPORT_MD_FILENAME).read_text(encoding="utf-8")

    assert "`broken-trial` — agent-a — FAIL" in markdown
    assert "agent crashed" in markdown


def test_generate_report_markdown_shows_behavior_profile_per_trial(tmp_path: Path) -> None:
    """AAASM-4406 AC1: a trial that targets a `BehaviorProfile` shows its
    `behavior_id` in the rendered Markdown, distinct from a trial that
    doesn't (which shows `(default)` rather than a forced/fabricated value).
    """
    targeted_trial = _trial(
        id="injection-trial",
        expected={"some.action": Decision.DENY},
        behavior_id="prompt-injection-vulnerable",
    )
    scenario = _scenario(trial_ids=[targeted_trial.id])
    workspace = tmp_path / "runs" / _MATCH_ID
    match_result = _match_result(
        scenario=scenario,
        trial_outcomes=[_outcome(trial=targeted_trial, agent_id="agent-a")],
        workspace=workspace,
    )
    audit_events = [
        _decided_event(trial_id=targeted_trial.id, tool="some.action", effect=Decision.DENY)
    ]
    score = score_match(match_result, scenario, audit_events)

    report_dir = generate_report(
        match_result, score, audit_events, reports_root=tmp_path / "reports"
    )
    markdown = (report_dir / ARENA_REPORT_MD_FILENAME).read_text(encoding="utf-8")

    assert "- **Behavior profile:** prompt-injection-vulnerable" in markdown


# --- JSON content ----------------------------------------------------------------


def test_generate_report_json_round_trips_and_has_schema_version(tmp_path: Path) -> None:
    match_result, audit_events = _standard_match(tmp_path / "runs" / _MATCH_ID)
    score = score_match(match_result, match_result.scenario, audit_events)
    reports_root = tmp_path / "reports"

    report_dir = generate_report(match_result, score, audit_events, reports_root=reports_root)
    raw = (report_dir / ARENA_REPORT_JSON_FILENAME).read_text(encoding="utf-8")
    payload = json.loads(raw)

    assert payload["schema_version"] == SCHEMA_VERSION
    assert payload["match_id"] == _MATCH_ID
    assert payload["agents"] == ["agent-a"]

    round_tripped = MatchReport.model_validate(payload)
    assert round_tripped.match_id == _MATCH_ID
    assert round_tripped.score.outcome is MatchOutcome.AGENT_ASSEMBLY_WINS
    assert len(round_tripped.trials) == 1


# --- JSONL content ---------------------------------------------------------------


def test_generate_report_jsonl_is_parseable_line_by_line(tmp_path: Path) -> None:
    trial = _trial(id="multi-trial", expected={"tool.a": Decision.ALLOW, "tool.b": Decision.DENY})
    scenario = _scenario(trial_ids=[trial.id])
    workspace = tmp_path / "runs" / _MATCH_ID
    match_result = _match_result(
        scenario=scenario, trial_outcomes=[_outcome(trial=trial)], workspace=workspace
    )
    audit_events = [
        _decided_event(trial_id=trial.id, tool="tool.a", effect=Decision.ALLOW),
        _decided_event(trial_id=trial.id, tool="tool.b", effect=Decision.DENY),
    ]
    score = score_match(match_result, scenario, audit_events)

    report_dir = generate_report(
        match_result, score, audit_events, reports_root=tmp_path / "reports"
    )
    lines = (report_dir / AUDIT_LOG_FILENAME).read_text(encoding="utf-8").strip().splitlines()

    assert len(lines) == 2
    parsed = [ArenaAuditEvent.model_validate(json.loads(line)) for line in lines]
    assert {event.attempt.tool for event in parsed if event.attempt is not None} == {
        "tool.a",
        "tool.b",
    }


# --- build_report: unattributed events ----------------------------------------


def test_build_report_collects_unattributed_parse_error_events(tmp_path: Path) -> None:
    trial = _trial(id="happy-trial", expected={"some.action": Decision.ALLOW})
    scenario = _scenario(trial_ids=[trial.id])
    match_result = _match_result(
        scenario=scenario,
        trial_outcomes=[_outcome(trial=trial)],
        workspace=tmp_path / "runs" / _MATCH_ID,
    )
    parse_error_event = ArenaAuditEvent.for_parse_error(
        match_id=_MATCH_ID, severity=Severity.LOW, error="malformed marker line"
    )
    audit_events = [
        _decided_event(trial_id=trial.id, tool="some.action"),
        parse_error_event,
    ]
    score = score_match(match_result, scenario, audit_events)

    report = build_report(match_result, score, audit_events)

    assert len(report.trials) == 1
    assert len(report.trials[0].audit_events) == 1
    assert report.unattributed_audit_events == (parse_error_event,)


# --- execution metadata (AAASM-4406) --------------------------------------------


def test_build_execution_metadata_defaults_to_mock_deterministic_zero_cost(tmp_path: Path) -> None:
    """AC4: a `mock`-mode match's report shows zero external model calls and
    zero estimated cost, matching the every-match default.
    """
    trial = _trial(id="happy-trial")
    scenario = _scenario(trial_ids=[trial.id])
    match_result = _match_result(
        scenario=scenario,
        trial_outcomes=[_outcome(trial=trial)],
        workspace=tmp_path / "runs" / _MATCH_ID,
    )

    execution = build_execution_metadata(match_result)

    assert execution.llm_mode is LLMMode.MOCK
    assert execution.deterministic is True
    assert execution.external_model_calls == 0
    assert execution.estimated_cost_usd == 0.0


def test_build_execution_metadata_replay_mode_is_also_deterministic_zero_cost(
    tmp_path: Path,
) -> None:
    """AC4 extended to `replay`: also zero-cost/zero-call by construction —
    only `live` may make a real model call.
    """
    trial = _trial(id="happy-trial")
    scenario = _scenario(trial_ids=[trial.id])
    match_result = _match_result(
        scenario=scenario,
        trial_outcomes=[_outcome(trial=trial)],
        workspace=tmp_path / "runs" / _MATCH_ID,
        llm_mode=LLMMode.REPLAY,
    )

    execution = build_execution_metadata(match_result)

    assert execution.llm_mode is LLMMode.REPLAY
    assert execution.deterministic is True
    assert execution.external_model_calls == 0
    assert execution.estimated_cost_usd == 0.0


def test_build_execution_metadata_live_mode_is_marked_non_deterministic(tmp_path: Path) -> None:
    """AC3: a `live`-mode match's report is clearly marked non-deterministic."""
    trial = _trial(id="happy-trial")
    scenario = _scenario(trial_ids=[trial.id])
    match_result = _match_result(
        scenario=scenario,
        trial_outcomes=[_outcome(trial=trial)],
        workspace=tmp_path / "runs" / _MATCH_ID,
        llm_mode=LLMMode.LIVE,
    )

    execution = build_execution_metadata(match_result)

    assert execution.llm_mode is LLMMode.LIVE
    assert execution.deterministic is False


def test_build_execution_metadata_live_mode_reflects_configured_budget_guards(
    tmp_path: Path,
) -> None:
    trial = _trial(id="happy-trial")
    scenario = _scenario(trial_ids=[trial.id])
    match_result = _match_result(
        scenario=scenario,
        trial_outcomes=[_outcome(trial=trial)],
        workspace=tmp_path / "runs" / _MATCH_ID,
        llm_mode=LLMMode.LIVE,
        max_live_calls=5,
        max_cost_usd=1.25,
    )

    execution = build_execution_metadata(match_result)

    assert execution.external_model_calls == 5
    assert execution.estimated_cost_usd == 1.25


def test_build_execution_metadata_live_mode_without_budget_guards_is_null(
    tmp_path: Path,
) -> None:
    """No call-counting infrastructure exists yet (AAASM-4405's own scope
    note) — a `live` match with no configured budget guard genuinely has no
    number to report, so this is `None` ("unknown"), not a fabricated `0`.
    """
    trial = _trial(id="happy-trial")
    scenario = _scenario(trial_ids=[trial.id])
    match_result = _match_result(
        scenario=scenario,
        trial_outcomes=[_outcome(trial=trial)],
        workspace=tmp_path / "runs" / _MATCH_ID,
        llm_mode=LLMMode.LIVE,
    )

    execution = build_execution_metadata(match_result)

    assert execution.external_model_calls is None
    assert execution.estimated_cost_usd is None


def test_build_report_execution_field_matches_build_execution_metadata(tmp_path: Path) -> None:
    """AC2: the JSON-serializable `MatchReport.execution` is exactly what
    `build_execution_metadata` derives for the same `MatchResult`.
    """
    trial = _trial(id="happy-trial")
    scenario = _scenario(trial_ids=[trial.id])
    match_result = _match_result(
        scenario=scenario,
        trial_outcomes=[_outcome(trial=trial)],
        workspace=tmp_path / "runs" / _MATCH_ID,
        llm_mode=LLMMode.LIVE,
        max_live_calls=3,
        max_cost_usd=0.5,
    )
    audit_events = [_decided_event(trial_id=trial.id, tool="some.action")]
    score = score_match(match_result, scenario, audit_events)

    report = build_report(match_result, score, audit_events)

    assert report.execution == build_execution_metadata(match_result)


# --- behavior_id per trial (AAASM-4406) -----------------------------------------


def test_build_report_trial_behavior_id_reflects_trial_spec(tmp_path: Path) -> None:
    """AC1/AC2: `TrialReport.behavior_id` mirrors `TrialSpec.behavior_id`
    when the trial targets a `BehaviorProfile`, and stays `None` when it
    doesn't — never forced to a value either way.
    """
    targeted_trial = _trial(id="targeted-trial", behavior_id="secret-seeking")
    plain_trial = _trial(id="plain-trial", expected={"other.action": Decision.ALLOW})
    scenario = _scenario(trial_ids=[targeted_trial.id, plain_trial.id])
    match_result = _match_result(
        scenario=scenario,
        trial_outcomes=[
            _outcome(trial=targeted_trial, agent_id="agent-a"),
            _outcome(trial=plain_trial, agent_id="agent-a"),
        ],
        workspace=tmp_path / "runs" / _MATCH_ID,
    )
    audit_events = [
        _decided_event(trial_id=targeted_trial.id, tool="some.action"),
        _decided_event(trial_id=plain_trial.id, tool="other.action"),
    ]
    score = score_match(match_result, scenario, audit_events)

    report = build_report(match_result, score, audit_events)

    by_trial_id = {trial.trial_id: trial for trial in report.trials}
    assert by_trial_id["targeted-trial"].behavior_id == "secret-seeking"
    assert by_trial_id["plain-trial"].behavior_id is None
