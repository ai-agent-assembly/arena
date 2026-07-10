"""`DefenseDecision`: the governance verdict agent-assembly renders for one
`ArenaActionAttempt`, as returned by an `AgentAssemblyClient`
(`arena.integrations.adapter`).

This is the next link in AAASM-4377's chain: `ArenaActionAttempt`
(AAASM-4379) -> agent-assembly adapter (AAASM-4378, this model is its output)
-> `DefenseDecision` -> Arena audit event (AAASM-4380) -> report model. The
Story's own acceptance criteria requires Arena to "preserve decision reason,
policy ID, layer, severity, and obligations if provided" — this model is
exactly that preserved shape, independent of whatever transport a concrete
`AgentAssemblyClient` implementation used to obtain it.
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field

from arena.models.scenario import Decision, Severity


class DefenseDecision(BaseModel):
    """One governance verdict agent-assembly rendered for an `ArenaActionAttempt`.

    `extra="forbid"` and `frozen=True` mirror `ArenaActionAttempt`'s own
    convention (see `arena.integrations.models`): a decision describes
    something agent-assembly already rendered and should never be silently
    mutated after the fact.

    Fields:
        effect: The verdict itself — reuses `arena.models.scenario.Decision`
            rather than redefining an equivalent enum, since a
            `DefenseDecision.effect` and a `TrialSpec.expected` value must be
            directly comparable to score a trial.
        layer: Which governance layer produced this decision (e.g.
            `"policy"`, `"budget"`). Kept as a plain string rather than a
            closed enum — agent-assembly's own layer taxonomy is not
            Arena's concern to hardcode; a real adapter implementation can
            pass through whatever layer name its transport reports.
        reason: Human-readable rationale for the decision, for reporting and
            audit review.
        policy_id: The specific policy rule that produced this decision, if
            the layer that rendered it is policy-driven and reports one.
            `None` when not applicable/available.
        severity: Reuses `arena.models.scenario.Severity` — how critical this
            decision was, independent of `TrialSpec.severity` (which
            describes the trial's expected criticality rather than what was
            actually decided), so a real decision's own reported severity
            can be preserved and compared against the trial's expectation.
        obligations: Follow-up instructions attached to the decision (e.g.
            redaction instructions for a `REDACT` effect). A plain
            `list[str]` of human-readable descriptions is sufficient for
            Arena's own audit/report needs; nothing here requires a more
            structured obligation model.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    effect: Decision
    layer: str = Field(min_length=1)
    reason: str = Field(min_length=1)
    policy_id: str | None = None
    severity: Severity
    obligations: list[str] = Field(default_factory=list)
