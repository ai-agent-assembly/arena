"""`ArenaActionAttempt`: the common event model every agent framework's
attempted action gets normalized into before it can be handed to
agent-assembly for a governance decision or persisted for a match report.

This is the foundational seam AAASM-4377's chain of subtasks builds on:
AAASM-4378's agent-assembly adapter consumes instances of this model as
input, AAASM-4380's audit pipeline persists them, and AAASM-4381's contract
tests assert every attempt has a corresponding decision. See
`arena.integrations.emit` for how an agent process actually produces one of
these from inside its own OS process, and `arena.integrations.parser` for
how Arena recovers instances of this model from an agent's captured stdout.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class ArenaActionAttempt(BaseModel):
    """One agent's attempt at one governed action.

    Framework-agnostic by design: nothing here assumes raw Python,
    LangGraph, PydanticAI, CrewAI, or any other agent framework's own
    internal representation — every framework's attempts flatten to the
    same fields, which is exactly what lets a single agent-assembly adapter
    (AAASM-4378) and audit pipeline (AAASM-4380) handle all of them
    uniformly.

    `extra="forbid"` and `frozen=True` mirror the existing convention in
    this codebase for immutable historical-record models (see
    `TrialSpec`/`AgentRunResult`) — an action attempt describes something
    that already happened and should never be silently mutated after the
    fact.

    Fields:
        agent_id: The attempting agent's manifest id (`AgentManifest.id`).
        framework: The agent's framework family (e.g. `"raw-python"`,
            `"langgraph"`). Kept as a plain string rather than
            `arena.models.manifest.AgentFramework` so this model — and the
            emit-side helper that builds it — has no dependency on the
            manifest schema; a call site that only knows its own framework
            name as a string (which is all any framework needs) can still
            produce a valid attempt.
        scenario_id: The scenario the attempt happened within.
        trial_id: The specific trial (`TrialSpec.id`) being attempted.
        tool: The action/tool identifier, matching the style of
            `TrialSpec.expected`'s keys (e.g. `"github.contents.write"`).
        resource: The specific resource the action targets (a path, issue
            id, release tag, etc. — whatever `tool` operates on).
        args: The arguments/payload the agent attempted to pass to `tool`.
            Must be JSON-serializable; this is the caller's responsibility,
            not something this model enforces beyond what `dict[str, Any]`
            already implies.
        context: A free-text rationale/description of why the agent
            attempted this — useful for reporting and for a human reviewing
            a match's audit trail, optional since not every attempt needs
            one.
        timestamp: When the attempt was made. Defaults to "now" (UTC) at
            construction time so a typical call site doesn't need to supply
            one itself.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    agent_id: str = Field(min_length=1)
    framework: str = Field(min_length=1)
    scenario_id: str = Field(min_length=1)
    trial_id: str = Field(min_length=1)
    tool: str = Field(min_length=1)
    resource: str = Field(min_length=1)
    args: dict[str, Any] = Field(default_factory=dict)
    context: str | None = None
    timestamp: datetime = Field(default_factory=lambda: datetime.now(UTC))
