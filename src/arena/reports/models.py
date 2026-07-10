"""Pydantic v2 models for `arena-report.json`: a stable, versioned schema for
one completed match's report, built on top of `MatchScore` (AAASM-4389).

This is AAASM-4390, the second link in AAASM-4388's report/scoring Story —
`arena.reports.generate.generate_report` turns a `MatchResult` + `MatchScore`
+ the match's `ArenaAuditEvent`s into a `MatchReport` instance using this
module, then serializes it to `arena-report.json` (and reuses the same
`MatchReport` to drive `arena.reports.markdown.render_markdown`'s
`arena-report.md`). AAASM-4391 (snapshot tests) will assert against whatever
shape `MatchReport` has at that point — see `SCHEMA_VERSION`'s docstring for
why that matters.

These models reuse `ArenaAuditEvent`/`MatchScore`/`VictoryConditions` rather
than re-declaring equivalent shadow fields — a `TrialReport.audit_events`
entry is exactly the same `ArenaAuditEvent` `arena.integrations.audit`
already defines (including its own redaction guarantee — see
`arena.integrations.audit._persisted_payload`), not a re-derived summary of
one.
"""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field

from arena.integrations.audit import ArenaAuditEvent
from arena.models.scenario import Decision, Severity, VictoryConditions
from arena.reports.scoring import MatchScore

#: The `arena-report.json` schema version, persisted verbatim as
#: `MatchReport.schema_version`. A plain string (not an int) so a future
#: bump can move to "1.1"/"2" freely without a type change. AAASM-4391's
#: snapshot tests pin their expectations to whatever this module ships with
#: at that point — bumping it is a deliberate, visible schema change, not
#: an implementation detail.
SCHEMA_VERSION = "1"


class TrialReport(BaseModel):
    """One (agent, trial) run's full detail: the trial's own spec fields
    needed for display, its `TrialOutcome` verdict, and every
    `ArenaAuditEvent` attributable to this (agent, trial) pair.

    `extra="forbid"` and `frozen=True` mirror the rest of this codebase's
    convention for models describing something that already happened.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    trial_id: str = Field(min_length=1)
    agent_id: str = Field(min_length=1)
    description: str = Field(min_length=1)
    severity: Severity
    expected: dict[str, Decision]
    passed: bool
    error: str | None = None
    exit_code: int
    duration_seconds: float
    audit_events: tuple[ArenaAuditEvent, ...] = Field(default_factory=tuple)


class MatchReport(BaseModel):
    """The full report for one completed match: metadata, scenario, agents,
    every trial's detail, the match's `MatchScore`, and any audit events
    that couldn't be attributed to a specific (agent, trial) pair.

    Fields:
        schema_version: See `SCHEMA_VERSION`.
        match_id: `MatchResult.match_id`.
        scenario_id/scenario_name/scenario_description: `ScenarioSpec`'s own
            identifying fields, flattened rather than nesting the whole
            `ScenarioSpec` — a report reader wants the scenario's identity
            and blurb, not its `trials`/`victory_conditions` internals
            (the latter is already surfaced via `victory_conditions` below).
        timestamp: When the match started (`MatchEventType.MATCH_STARTED`'s
            own timestamp).
        agents: Every distinct agent id that ran a trial in this match,
            sorted for deterministic output.
        victory_conditions: The scenario's own thresholds, so a report
            reader can see counts next to what they were judged against
            without cross-referencing the scenario file.
        score: The full `MatchScore` — six failure counts plus the final
            verdict.
        trials: One `TrialReport` per `TrialOutcome` in the match, in the
            same (agent, trial) iteration order `run_match` produced.
        unattributed_audit_events: `ArenaAuditEvent`s with no `attempt`
            (parse-error events — see `ArenaAuditEvent.for_parse_error`) that
            therefore can't be linked to a specific (agent, trial) pair.
            Surfaced here rather than silently dropped.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_version: str = Field(default=SCHEMA_VERSION, min_length=1)
    match_id: str = Field(min_length=1)
    scenario_id: str = Field(min_length=1)
    scenario_name: str = Field(min_length=1)
    scenario_description: str = Field(min_length=1)
    timestamp: datetime
    agents: tuple[str, ...]
    victory_conditions: VictoryConditions
    score: MatchScore
    trials: tuple[TrialReport, ...]
    unattributed_audit_events: tuple[ArenaAuditEvent, ...] = Field(default_factory=tuple)
