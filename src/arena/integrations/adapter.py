"""`AgentAssemblyClient`: the transport-neutral seam through which Arena asks
agent-assembly for a governance decision on one `ArenaActionAttempt`.

**Design rationale.** AAASM-4377's proposed design deliberately does not
hardcode a single transport: "The adapter can initially support a
fake/local implementation for deterministic MVP tests and a real
implementation for the actual agent-assembly gateway/CLI/SDK contract when
available." `AgentAssemblyClient` is that seam — a `Protocol` whose only
contract is "given an attempt, return a decision (or raise)". Nothing in the
Protocol itself assumes HTTP, gRPC, a CLI subprocess, or an in-process SDK
call; that's entirely a concrete implementation's job. `FakeAgentAssemblyClient`
is the one concrete implementation this ticket builds — a deterministic,
in-memory backend for MVP/CI use, per AAASM-4377's "Support fake decisions
for MVP and tests" scope item. A real implementation (the actual
agent-assembly gateway/CLI/SDK contract) is explicitly out of scope for this
Story ("Building real external connectors in Arena") and does not exist yet.

**Fail-closed by construction.** AAASM-4377's acceptance criteria requires
"Missing decisions are treated as reportable failures" — silently defaulting
a missing/invalid decision to `Decision.ALLOW` would itself be a governance
bypass, exactly the kind of gap AAASM-4381's future contract tests exist to
catch. `FakeAgentAssemblyClient.decide` raises `MissingDecisionError` rather
than returning a sentinel or defaulting, so a caller that forgets to handle
it fails loudly (an uncaught exception) instead of silently proceeding as if
an action were allowed.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from enum import Enum
from typing import Protocol, runtime_checkable

from arena.integrations.decision import DefenseDecision
from arena.integrations.models import ArenaActionAttempt
from arena.models.scenario import TrialSpec


class MissingDecisionError(Exception):
    """Raised by an `AgentAssemblyClient` when no decision is available for
    a given `ArenaActionAttempt`.

    Callers must treat this as a reportable Arena failure (per AAASM-4377's
    acceptance criteria), never catch-and-default to `Decision.ALLOW`.
    """


@runtime_checkable
class AgentAssemblyClient(Protocol):
    """Transport-neutral contract for obtaining a governance decision.

    An implementation may call out to agent-assembly over any transport
    (HTTP, gRPC, a CLI subprocess, an in-process SDK call) or, like
    `FakeAgentAssemblyClient`, return canned decisions with no external call
    at all — the Protocol says nothing about how `decide` gets its answer,
    only what it returns.
    """

    def decide(self, attempt: ArenaActionAttempt) -> DefenseDecision:
        """Return the governance decision for `attempt`.

        Raises:
            MissingDecisionError: no decision is available for `attempt`.
                Implementations must raise rather than fabricate a decision
                (e.g. defaulting to `Decision.ALLOW`) — see the module
                docstring's "Fail-closed by construction" note.
        """
        ...


@dataclass(frozen=True)
class FakeAgentAssemblyClient:
    """Deterministic, in-memory `AgentAssemblyClient` for MVP/CI use.

    Configured with a mapping from `(trial_id, tool)` to the canned
    `DefenseDecision` that attempt should receive. Keying on both
    `trial_id` and `tool` (rather than `trial_id` alone) mirrors
    `TrialSpec.expected`, which maps *per-action* keys to a `Decision`
    within a single trial — a trial can exercise more than one tool/action,
    each with its own expected verdict, so a single per-trial decision would
    be insufficient. `tool` alone would also be insufficient, since the same
    tool name can recur across trials with different expected outcomes.

    See `from_trial_spec` for the intended way to build one of these in
    tests: from a real `TrialSpec.expected` mapping, which is already the
    natural source of truth for "what should this trial's decision be."
    """

    decisions: Mapping[tuple[str, str], DefenseDecision] = field(default_factory=dict)

    def decide(self, attempt: ArenaActionAttempt) -> DefenseDecision:
        key = (attempt.trial_id, attempt.tool)
        decision = self.decisions.get(key)
        if decision is None:
            raise MissingDecisionError(
                f"no configured decision for trial_id={attempt.trial_id!r}, tool={attempt.tool!r}"
            )
        return decision

    @classmethod
    def from_trial_spec(
        cls,
        trial: TrialSpec,
        *,
        layer: str = "policy",
        policy_id: str | None = None,
        obligations_by_action: Mapping[str, list[str]] | None = None,
    ) -> FakeAgentAssemblyClient:
        """Build a fake client whose decisions come straight from `trial.expected`.

        For every `action -> Decision` entry in `trial.expected`, configures
        a `DefenseDecision` with that `effect`, `trial.severity` as its
        `severity`, and a generated `reason`. `layer`/`policy_id` apply
        uniformly to every generated decision; `obligations_by_action` lets a
        caller attach obligations (e.g. redaction instructions) to specific
        actions by key — actions with no entry get an empty obligations list.
        """
        obligations = obligations_by_action or {}
        decisions = {
            (trial.id, action): DefenseDecision(
                effect=effect,
                layer=layer,
                reason=f"expected decision for trial {trial.id!r}, action {action!r}",
                policy_id=policy_id,
                severity=trial.severity,
                obligations=list(obligations.get(action, [])),
            )
            for action, effect in trial.expected.items()
        }
        return cls(decisions=decisions)


class AdapterChoice(str, Enum):
    """Which `AgentAssemblyClient` implementation to use."""

    FAKE = "fake"
    REAL = "real"


def build_agent_assembly_client(choice: AdapterChoice) -> AgentAssemblyClient:
    """Construct the `AgentAssemblyClient` for `choice`.

    Raises:
        NotImplementedError: `choice` is `AdapterChoice.REAL` — building a
            real external connector to agent-assembly's own gateway/CLI/SDK
            is out of scope for this Story (AAASM-4377's "Out of Scope:
            Building real external connectors in Arena"); only the fake
            backend exists today.
    """
    if choice is AdapterChoice.FAKE:
        return FakeAgentAssemblyClient()
    raise NotImplementedError(
        "the 'real' agent-assembly adapter is not implemented — building real "
        "external connectors in Arena is out of scope (see AAASM-4377)"
    )
