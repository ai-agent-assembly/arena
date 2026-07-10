"""The `Runner` seam between match orchestration and agent execution backends.

This is the interface AAASM-4374 (process runner) and AAASM-4375 (Docker
runner) build against. Match orchestration (`arena.runner.match`) only needs
to launch one agent for one trial and get a uniform result back — everything
about *how* that launch happens (subprocess, container, timeout policy,
network access) is a `Runner` implementation's concern, not orchestration's.
This module intentionally stays minimal: it defines the contract, not a
shared base class or execution machinery, so each execution backend is free
to implement it however it needs to.
"""

from __future__ import annotations

from pathlib import Path
from typing import Protocol, runtime_checkable

from pydantic import BaseModel, ConfigDict

from arena.models.manifest import AgentManifest
from arena.models.scenario import TrialSpec


class AgentRunResult(BaseModel):
    """What a `Runner` reports back for one agent's attempt at one trial.

    Deliberately does not include anything about whether the resulting
    governance *decision* was correct — comparing captured behavior against
    `TrialSpec.expected` decisions is an agent-assembly integration concern
    (AAASM-4377), not the runner's.
    """

    model_config = ConfigDict(frozen=True)

    exit_code: int
    stdout: str
    stderr: str
    duration_seconds: float


@runtime_checkable
class Runner(Protocol):
    """Launches one agent for one trial and reports back what happened.

    Implementations own the actual execution boundary (subprocess, container,
    etc.). `run` is expected to be synchronous, and to prefer a non-zero
    `AgentRunResult.exit_code` over raising for an ordinary agent failure —
    match orchestration treats a raised exception as an execution-backend
    bug, not a normal trial outcome, and reports it as an error rather than
    letting it crash the rest of the match (see AAASM-4372's "failed agent
    process does not crash the whole runner" acceptance criterion). Any
    transient output should be written under `workspace`, which the caller
    creates before invoking this.
    """

    def run(
        self,
        manifest: AgentManifest,
        trial: TrialSpec,
        *,
        workspace: Path,
    ) -> AgentRunResult: ...
