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
from arena.runner.llm_mode import LLMMode

#: The `arena-report.json` schema version, persisted verbatim as
#: `MatchReport.schema_version`. A plain string (not an int) so a future
#: bump can move to "1.1"/"2" freely without a type change. AAASM-4391's
#: snapshot tests pin their expectations to whatever this module ships with
#: at that point — bumping it is a deliberate, visible schema change, not
#: an implementation detail.
#:
#: Bumped "1" -> "2" by AAASM-4406: `MatchReport.execution` (a new
#: *required* field — see `ExecutionMetadata`) means a schema-"1" payload
#: with no `execution` key no longer validates as a `MatchReport` at all,
#: not just an additive/ignorable field a consumer could skip — exactly the
#: "deliberate, visible schema change" this constant exists to signal.
SCHEMA_VERSION = "2"


class ExecutionMetadata(BaseModel):
    """How a match's agents were allowed to interact with LLMs (AAASM-4405),
    recorded on `MatchReport` so a report reader can see at a glance whether
    a match's results are reproducible.

    This subtask (AAASM-4406) only *records* what `MatchConfig` already
    decided before/during the match — it does not add any new enforcement
    or call-counting infrastructure. `external_model_calls`/
    `estimated_cost_usd` are therefore metadata, not measured counters:

    * Under `LLMMode.MOCK`/`LLMMode.REPLAY`, both are always `0`/`0.0` — no
      real model call is possible in either mode by construction (see
      `arena.runner.llm_mode`'s module docstring), independent of whatever
      budget-guard fields a `MatchConfig` happens to carry.
    * Under `LLMMode.LIVE`, both mirror `MatchConfig.max_live_calls`/
      `max_cost_usd` (the only live-mode data available today — see
      `MatchConfig`'s own docstring: those fields are consulted by nothing
      yet, no real call-counting pipeline exists). `None` means "no budget
      guard was configured, so there is no number to report" — a live match
      run without either flag set genuinely has no call/cost figure Arena
      can produce, and `None` says that honestly instead of a fabricated
      `0`.

    Fields:
        llm_mode: `MatchConfig.llm_mode` this match ran under.
        deterministic: `True` for `mock`/`replay` (no real model call is
            possible), `False` for `live` (a real model call can vary
            response-to-response) — derived from `llm_mode`, not a second
            independent input, so it can never disagree with it.
        external_model_calls: See above.
        estimated_cost_usd: See above.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    llm_mode: LLMMode
    deterministic: bool
    external_model_calls: int | None = 0
    estimated_cost_usd: float | None = 0.0


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
    #: `TrialSpec.behavior_id` (AAASM-4404) in effect for this (agent,
    #: trial) run — `None` when the trial doesn't target a specific
    #: `BehaviorProfile`, which is valid and common (most trials written
    #: before AAASM-4404, and any scenario that doesn't care about behavior
    #: profiles, never set one). Not forced to a value.
    behavior_id: str | None = None
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
        execution: The `LLMMode` (AAASM-4405) this match's agents ran under,
            plus whether the result is deterministic — see
            `ExecutionMetadata`.
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
    execution: ExecutionMetadata
