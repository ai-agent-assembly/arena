"""Structured match lifecycle events.

Emitted in order by `arena.runner.match.run_match` so that a later
report-generation ticket has something structured to consume — Pydantic
models with a stable schema — instead of parsing CLI output.
"""

from __future__ import annotations

from datetime import datetime
from enum import Enum

from pydantic import BaseModel, ConfigDict, Field

#: JSON-safe scalar type for free-form event payload values in `MatchEvent.data`.
EventValue = str | int | float | bool | None


class MatchEventType(str, Enum):
    """The lifecycle events a match emits, in emission order per AAASM-4372."""

    MATCH_STARTED = "match_started"
    TRIAL_STARTED = "trial_started"
    AGENT_STARTED = "agent_started"
    AGENT_FINISHED = "agent_finished"
    TRIAL_FINISHED = "trial_finished"
    MATCH_FINISHED = "match_finished"


class MatchEvent(BaseModel):
    """One lifecycle event in a match's timeline.

    `scenario_id`/`agent_id`/`trial_id` are populated when the event applies
    to that scope (e.g. `trial_started` always has `agent_id` and `trial_id`;
    `match_started`/`match_finished` only have `scenario_id`). `data` carries
    event-specific detail (exit codes, counts, error text) that doesn't
    warrant its own dedicated field.
    """

    model_config = ConfigDict(frozen=True)

    type: MatchEventType
    match_id: str
    timestamp: datetime
    scenario_id: str | None = None
    agent_id: str | None = None
    trial_id: str | None = None
    data: dict[str, EventValue] = Field(default_factory=dict)
