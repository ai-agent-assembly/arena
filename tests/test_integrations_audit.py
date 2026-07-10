"""Unit tests for `ArenaAuditEvent` and the append-only JSONL audit log
(AAASM-4380): event construction via the `for_decision`/`for_missing_decision`/
`for_parse_error` factories, append-only/replayable JSONL persistence, and
redaction of `attempt.args` when a decision is `REDACT`.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from pydantic import ValidationError

from arena.integrations.audit import (
    REDACTION_MARKER,
    ArenaAuditEvent,
    AuditEventStatus,
    append_audit_event,
    read_audit_events,
)
from arena.integrations.decision import DefenseDecision
from arena.integrations.models import ArenaActionAttempt
from arena.models.scenario import Decision, Severity

_ALL_DECISIONS = list(Decision)


def _attempt(
    *, tool: str = "github.contents.write", args: dict[str, str] | None = None
) -> ArenaActionAttempt:
    return ArenaActionAttempt(
        agent_id="agent-a",
        framework="raw-python",
        scenario_id="github-maintainer-dungeon",
        trial_id="trial-a",
        tool=tool,
        resource="src/app.py",
        args=args or {},
    )


def _decision(effect: Decision, *, severity: Severity = Severity.HIGH) -> DefenseDecision:
    return DefenseDecision(
        effect=effect,
        layer="policy",
        reason=f"canned decision for {effect.value}",
        severity=severity,
    )


# --- ArenaAuditEvent factories -----------------------------------------------


def test_for_decision_builds_decided_event() -> None:
    attempt = _attempt()
    decision = _decision(Decision.DENY, severity=Severity.CRITICAL)

    event = ArenaAuditEvent.for_decision(match_id="match-1", attempt=attempt, decision=decision)

    assert event.match_id == "match-1"
    assert event.attempt == attempt
    assert event.decision == decision
    assert event.status is AuditEventStatus.DECIDED
    assert event.severity is Severity.CRITICAL
    assert event.error is None


def test_for_missing_decision_builds_event_with_attempt_and_no_decision() -> None:
    attempt = _attempt()

    event = ArenaAuditEvent.for_missing_decision(
        match_id="match-1", attempt=attempt, severity=Severity.LOW, error="no configured decision"
    )

    assert event.attempt == attempt
    assert event.decision is None
    assert event.status is AuditEventStatus.MISSING_DECISION
    assert event.severity is Severity.LOW
    assert event.error == "no configured decision"


def test_for_parse_error_builds_event_with_no_attempt() -> None:
    event = ArenaAuditEvent.for_parse_error(
        match_id="match-1", severity=Severity.MEDIUM, error="line 3: invalid JSON"
    )

    assert event.attempt is None
    assert event.decision is None
    assert event.status is AuditEventStatus.MISSING_DECISION
    assert event.severity is Severity.MEDIUM
    assert event.error == "line 3: invalid JSON"


def test_event_is_frozen() -> None:
    event = ArenaAuditEvent.for_decision(
        match_id="match-1", attempt=_attempt(), decision=_decision(Decision.ALLOW)
    )

    with pytest.raises(ValidationError):
        event.match_id = "match-2"


def test_unknown_field_is_rejected() -> None:
    with pytest.raises(ValidationError):
        ArenaAuditEvent(  # type: ignore[call-arg]
            match_id="match-1",
            status=AuditEventStatus.DECIDED,
            severity=Severity.LOW,
            unexpected="nope",
        )


# --- append_audit_event / read_audit_events ----------------------------------


def test_append_audit_event_writes_one_json_line(tmp_path: Path) -> None:
    path = tmp_path / "audit.jsonl"
    event = ArenaAuditEvent.for_decision(
        match_id="match-1", attempt=_attempt(), decision=_decision(Decision.ALLOW)
    )

    append_audit_event(path, event)

    lines = path.read_text(encoding="utf-8").splitlines()
    assert len(lines) == 1
    payload = json.loads(lines[0])
    assert payload["match_id"] == "match-1"
    assert payload["status"] == "decided"


def test_append_audit_event_creates_parent_directories(tmp_path: Path) -> None:
    path = tmp_path / "nested" / "deeper" / "audit.jsonl"
    event = ArenaAuditEvent.for_decision(
        match_id="match-1", attempt=_attempt(), decision=_decision(Decision.ALLOW)
    )

    append_audit_event(path, event)

    assert path.is_file()


def test_append_audit_event_is_append_only_across_multiple_calls(tmp_path: Path) -> None:
    path = tmp_path / "audit.jsonl"
    first = ArenaAuditEvent.for_decision(
        match_id="match-1", attempt=_attempt(tool="tool.a"), decision=_decision(Decision.ALLOW)
    )
    second = ArenaAuditEvent.for_decision(
        match_id="match-1", attempt=_attempt(tool="tool.b"), decision=_decision(Decision.DENY)
    )
    third = ArenaAuditEvent.for_missing_decision(
        match_id="match-1", attempt=_attempt(tool="tool.c"), severity=Severity.LOW, error="boom"
    )

    append_audit_event(path, first)
    append_audit_event(path, second)
    append_audit_event(path, third)

    lines = path.read_text(encoding="utf-8").splitlines()
    assert len(lines) == 3
    # Every line is independently json.loads()-able — not a single JSON array.
    parsed = [json.loads(line) for line in lines]
    assert [p["attempt"]["tool"] for p in parsed] == ["tool.a", "tool.b", "tool.c"]


def test_read_audit_events_round_trips(tmp_path: Path) -> None:
    path = tmp_path / "audit.jsonl"
    events = [
        ArenaAuditEvent.for_decision(
            match_id="match-1", attempt=_attempt(tool="tool.a"), decision=_decision(Decision.ALLOW)
        ),
        ArenaAuditEvent.for_missing_decision(
            match_id="match-1",
            attempt=_attempt(tool="tool.b"),
            severity=Severity.HIGH,
            error="boom",
        ),
        ArenaAuditEvent.for_parse_error(
            match_id="match-1", severity=Severity.LOW, error="line 2: bad json"
        ),
    ]
    for event in events:
        append_audit_event(path, event)

    restored = read_audit_events(path)

    assert len(restored) == 3
    assert restored[0].status is AuditEventStatus.DECIDED
    assert restored[0].decision is not None
    assert restored[0].decision.effect is Decision.ALLOW
    assert restored[1].status is AuditEventStatus.MISSING_DECISION
    assert restored[1].attempt is not None
    assert restored[2].attempt is None


def test_read_audit_events_returns_empty_list_for_missing_file(tmp_path: Path) -> None:
    assert read_audit_events(tmp_path / "does-not-exist.jsonl") == []


# --- redaction ----------------------------------------------------------------


def test_redact_decision_replaces_persisted_args(tmp_path: Path) -> None:
    path = tmp_path / "audit.jsonl"
    attempt = _attempt(args={"body": "sk-fake-secret-value", "issue": "42"})
    event = ArenaAuditEvent.for_decision(
        match_id="match-1", attempt=attempt, decision=_decision(Decision.REDACT)
    )

    append_audit_event(path, event)

    persisted = json.loads(path.read_text(encoding="utf-8").splitlines()[0])
    assert persisted["attempt"]["args"] == {"body": REDACTION_MARKER, "issue": REDACTION_MARKER}


@pytest.mark.parametrize("effect", [d for d in _ALL_DECISIONS if d is not Decision.REDACT])
def test_non_redact_decisions_leave_persisted_args_intact(tmp_path: Path, effect: Decision) -> None:
    path = tmp_path / "audit.jsonl"
    attempt = _attempt(args={"body": "plain value"})
    event = ArenaAuditEvent.for_decision(
        match_id="match-1", attempt=attempt, decision=_decision(effect)
    )

    append_audit_event(path, event)

    persisted = json.loads(path.read_text(encoding="utf-8").splitlines()[0])
    assert persisted["attempt"]["args"] == {"body": "plain value"}


def test_missing_decision_event_persists_without_redaction(tmp_path: Path) -> None:
    # No DefenseDecision at all — nothing to key redaction off of, so args
    # persist untouched.
    path = tmp_path / "audit.jsonl"
    attempt = _attempt(args={"body": "plain value"})
    event = ArenaAuditEvent.for_missing_decision(
        match_id="match-1", attempt=attempt, severity=Severity.LOW, error="boom"
    )

    append_audit_event(path, event)

    persisted = json.loads(path.read_text(encoding="utf-8").splitlines()[0])
    assert persisted["attempt"]["args"] == {"body": "plain value"}


def test_redaction_does_not_mutate_in_memory_event(tmp_path: Path) -> None:
    path = tmp_path / "audit.jsonl"
    attempt = _attempt(args={"body": "sk-fake-secret-value"})
    event = ArenaAuditEvent.for_decision(
        match_id="match-1", attempt=attempt, decision=_decision(Decision.REDACT)
    )

    append_audit_event(path, event)

    # The in-memory event (and its nested attempt) is untouched by
    # persistence-time redaction.
    assert event.attempt is not None
    assert event.attempt.args == {"body": "sk-fake-secret-value"}
    assert attempt.args == {"body": "sk-fake-secret-value"}
