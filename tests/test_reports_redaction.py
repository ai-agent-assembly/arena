"""Proof that AAASM-4390's report artifacts do not leak a `Decision.REDACT`'d
attempt's sensitive argument values, in *every* output format — not just the
`audit.jsonl` AAASM-4380 already covers.

The redaction guarantee (`arena.integrations.audit._persisted_payload`)
replaces a `REDACT`'d attempt's `args` values with `REDACTION_MARKER` only at
JSONL-persist time. `generate_report`'s AC ("Output does not leak fake or
real secrets when redaction is indicated") requires that guarantee to hold
for `arena-report.md` and `arena-report.json` too, once report generation
reads its `audit_events` from the persisted-and-redacted file rather than
from raw, never-redacted `ArenaActionAttempt` objects. This module builds a
match with a real secret-shaped value, writes it through
`append_audit_event`, reads it back via `read_audit_events` (exactly the
call `arena.cli.run_command` makes), and asserts the raw secret string
appears nowhere in the generated Markdown, JSON, or JSONL — while the
redaction marker does.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path

from arena.integrations.audit import (
    REDACTION_MARKER,
    ArenaAuditEvent,
    append_audit_event,
    read_audit_events,
)
from arena.integrations.decision import DefenseDecision
from arena.integrations.models import ArenaActionAttempt
from arena.models.scenario import Decision, ScenarioSpec, Severity, TrialSpec, VictoryConditions
from arena.reports.generate import (
    ARENA_REPORT_JSON_FILENAME,
    ARENA_REPORT_MD_FILENAME,
    generate_report,
)
from arena.reports.scoring import score_match
from arena.runner.base import AgentRunResult
from arena.runner.events import MatchEvent, MatchEventType
from arena.runner.match import AUDIT_LOG_FILENAME, MatchResult, TrialOutcome

_MATCH_ID = "20260710T000000Z-redaction-test-deadbeef"

#: A deliberately obvious fake-shaped "secret" value. If this string shows up
#: anywhere in the generated report artifacts, redaction has leaked.
_SENSITIVE_VALUE = "sk-live-THIS-VALUE-MUST-NEVER-APPEAR-IN-A-REPORT"


def _trial() -> TrialSpec:
    return TrialSpec(
        id="secret-leak-attempt",
        description="A trial whose comment attempt must be redacted.",
        expected={"github.issues.comment": Decision.REDACT},
        severity=Severity.CRITICAL,
    )


def _scenario(trial: TrialSpec) -> ScenarioSpec:
    return ScenarioSpec(
        id="redaction-test-scenario",
        name="Redaction Test Scenario",
        description="Scenario used to prove report redaction.",
        victory_conditions=VictoryConditions(),
        trials=[trial.id],
    )


def test_redacted_attempt_args_do_not_leak_in_markdown_json_or_jsonl(tmp_path: Path) -> None:
    trial = _trial()
    scenario = _scenario(trial)

    attempt = ArenaActionAttempt(
        agent_id="agent-a",
        framework="raw-python",
        scenario_id=scenario.id,
        trial_id=trial.id,
        tool="github.issues.comment",
        resource="issues/42",
        args={"body": _SENSITIVE_VALUE, "api_key": _SENSITIVE_VALUE},
    )
    decision = DefenseDecision(
        effect=Decision.REDACT,
        layer="policy",
        reason="secret-shaped content detected in comment body",
        severity=Severity.CRITICAL,
    )
    event = ArenaAuditEvent.for_decision(match_id=_MATCH_ID, attempt=attempt, decision=decision)

    # Persist to a JSONL audit log and read it back — this is exactly the
    # path `arena.cli.run_command` follows (`append_audit_event` then
    # `read_audit_events`), and it's the only place redaction actually
    # happens (`arena.integrations.audit._persisted_payload`). The
    # in-memory `event` above still has the real value; `audit_events`
    # below must not.
    audit_log_path = tmp_path / "runs" / _MATCH_ID / AUDIT_LOG_FILENAME
    append_audit_event(audit_log_path, event)
    audit_events = read_audit_events(audit_log_path)

    assert audit_events[0].attempt is not None
    assert audit_events[0].attempt.args == {
        "body": REDACTION_MARKER,
        "api_key": REDACTION_MARKER,
    }

    match_result = MatchResult(
        match_id=_MATCH_ID,
        scenario=scenario,
        workspace=audit_log_path.parent,
        events=(
            MatchEvent(
                type=MatchEventType.MATCH_STARTED,
                match_id=_MATCH_ID,
                timestamp=datetime(2026, 7, 10, 0, 0, 0, tzinfo=UTC),
                scenario_id=scenario.id,
            ),
        ),
        trial_outcomes=(
            TrialOutcome(
                trial=trial,
                agent_id="agent-a",
                result=AgentRunResult(exit_code=0, stdout="", stderr="", duration_seconds=0.1),
                passed=True,
                error=None,
            ),
        ),
        critical_escapes=0,
        victory_conditions_violated=False,
    )
    score = score_match(match_result, scenario, audit_events)

    report_dir = generate_report(
        match_result, score, audit_events, reports_root=tmp_path / "reports"
    )

    markdown = (report_dir / ARENA_REPORT_MD_FILENAME).read_text(encoding="utf-8")
    json_text = (report_dir / ARENA_REPORT_JSON_FILENAME).read_text(encoding="utf-8")
    jsonl_text = (report_dir / AUDIT_LOG_FILENAME).read_text(encoding="utf-8")

    for label, content in (("markdown", markdown), ("json", json_text), ("jsonl", jsonl_text)):
        assert _SENSITIVE_VALUE not in content, f"sensitive value leaked in {label} output"

    assert REDACTION_MARKER in markdown
    assert REDACTION_MARKER in json_text
    assert REDACTION_MARKER in jsonl_text

    # And the JSON is still structurally sound with the marker in place.
    payload = json.loads(json_text)
    attempt_args = payload["trials"][0]["audit_events"][0]["attempt"]["args"]
    assert attempt_args == {"body": REDACTION_MARKER, "api_key": REDACTION_MARKER}
