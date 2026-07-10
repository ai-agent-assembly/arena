"""`ArenaAuditEvent`: the persisted record of one governance decision (or
missing decision) for one `ArenaActionAttempt`.

This is the last new model in AAASM-4377's chain: `ArenaActionAttempt`
(AAASM-4379) -> agent-assembly adapter (AAASM-4378) -> `DefenseDecision` ->
`ArenaAuditEvent` (this ticket, AAASM-4380) -> report model (AAASM-4388+,
not built yet). `arena.runner.match.run_match` is the only caller today: for
every `ArenaActionAttempt` parsed from an agent's captured stdout, it will
call the configured `AgentAssemblyClient` and record exactly one
`ArenaAuditEvent` here — whether the adapter returned a real decision or
raised `MissingDecisionError` — plus one more per malformed marker line
`arena.integrations.parser.parse_action_attempts` couldn't even turn into an
`ArenaActionAttempt` in the first place. Persisting these to JSONL is
`arena.integrations.audit.append_audit_event`, added separately.

**Why embed rather than flatten.** `ArenaActionAttempt` already carries
`agent_id`/`framework`/`scenario_id`/`trial_id`/`timestamp`, and
`DefenseDecision` already carries `severity`/`policy_id`/`layer`/`reason`/
`obligations`. Re-declaring every one of those fields on this model would be
pure duplication with no value — a consumer that wants
`event.attempt.agent_id` or `event.decision.policy_id` already has it via
the nested objects. The one field promoted to the top level despite that is
`severity`, because it's needed by every consumer of this event regardless
of whether a decision was ever rendered (a `missing_decision` event may
have no `DefenseDecision` to read severity from) — see `for_decision`/
`for_missing_decision`/`for_parse_error` for exactly where each event's
`severity` comes from.
"""

from __future__ import annotations

from datetime import UTC, datetime
from enum import Enum

from pydantic import BaseModel, ConfigDict, Field

from arena.integrations.decision import DefenseDecision
from arena.integrations.models import ArenaActionAttempt
from arena.models.scenario import Severity


class AuditEventStatus(str, Enum):
    """Whether an `ArenaAuditEvent` carries a real decision or represents a
    missing one (either the adapter had no decision configured, or the
    marker line couldn't be parsed into an `ArenaActionAttempt` at all).
    """

    DECIDED = "decided"
    MISSING_DECISION = "missing_decision"


class ArenaAuditEvent(BaseModel):
    """One persisted audit record: one `ArenaActionAttempt` plus the
    `AgentAssemblyClient` outcome for it.

    `extra="forbid"` and `frozen=True` mirror `ArenaActionAttempt`/
    `DefenseDecision`'s own convention (see `arena.integrations.models`):
    an audit event describes something that already happened and should
    never be silently mutated after the fact.

    Prefer the `for_decision`/`for_missing_decision`/`for_parse_error`
    classmethods over calling the constructor directly — they encode which
    fields are required together for each of the three cases this model
    represents.

    Fields:
        match_id: The match this event belongs to — makes each JSONL line
            self-describing when read independently of the file it lives in
            (see `arena.runner.match.generate_match_id`).
        attempt: The `ArenaActionAttempt` this event is for. `None` only
            when the underlying marker line failed validation before an
            `ArenaActionAttempt` could even be constructed (a
            malformed-marker parse failure) — otherwise always present,
            regardless of whether a decision was obtained for it.
        decision: The `DefenseDecision` agent-assembly rendered, or `None`
            when `status` is `MISSING_DECISION`.
        status: `DECIDED` when `decision` is populated, `MISSING_DECISION`
            otherwise (no configured decision, or no parseable attempt).
        severity: See the module docstring's "Why embed rather than
            flatten" section.
        error: The `MissingDecisionError` message or parse-error message,
            when `status` is `MISSING_DECISION`. `None` otherwise.
        timestamp: When this event was recorded. Defaults to "now" (UTC).
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    match_id: str = Field(min_length=1)
    attempt: ArenaActionAttempt | None = None
    decision: DefenseDecision | None = None
    status: AuditEventStatus
    severity: Severity
    error: str | None = None
    timestamp: datetime = Field(default_factory=lambda: datetime.now(UTC))

    @classmethod
    def for_decision(
        cls, *, match_id: str, attempt: ArenaActionAttempt, decision: DefenseDecision
    ) -> ArenaAuditEvent:
        """Build a `DECIDED` event. `severity` comes straight from `decision.severity`."""
        return cls(
            match_id=match_id,
            attempt=attempt,
            decision=decision,
            status=AuditEventStatus.DECIDED,
            severity=decision.severity,
        )

    @classmethod
    def for_missing_decision(
        cls, *, match_id: str, attempt: ArenaActionAttempt, severity: Severity, error: str
    ) -> ArenaAuditEvent:
        """Build a `MISSING_DECISION` event for an attempt whose adapter call
        raised `MissingDecisionError`. `severity` must be supplied by the
        caller (typically the owning `TrialSpec.severity`) since there is no
        `DefenseDecision` to read it from.
        """
        return cls(
            match_id=match_id,
            attempt=attempt,
            decision=None,
            status=AuditEventStatus.MISSING_DECISION,
            severity=severity,
            error=error,
        )

    @classmethod
    def for_parse_error(cls, *, match_id: str, severity: Severity, error: str) -> ArenaAuditEvent:
        """Build a `MISSING_DECISION` event for a marker line that failed to
        parse into an `ArenaActionAttempt` at all (see
        `arena.integrations.parser.ActionAttemptParseResult.errors`).
        `attempt` is `None` since none could be constructed; `severity`
        must be supplied by the caller (typically the owning
        `TrialSpec.severity`).
        """
        return cls(
            match_id=match_id,
            attempt=None,
            decision=None,
            status=AuditEventStatus.MISSING_DECISION,
            severity=severity,
            error=error,
        )
