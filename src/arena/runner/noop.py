"""A placeholder `Runner` that does not actually launch anything.

This is **not** the real process runner — that is AAASM-4374's job, and a
Docker equivalent is AAASM-4375's. `NoOpRunner` exists only so match
orchestration (AAASM-4373) has a concrete `Runner` to invoke for its own
tests and for the AC's "smoke test can run a no-op official agent through
one trial." `default_runner_registry` in `arena.runner.match` wires this in
for every entrypoint type until AAASM-4374/4375 land; at that point it's
expected to be replaced as the default (it may stick around afterward only
as a test double).

Known limitation: `NoOpRunner` always reports `exit_code=0` and never
inspects `manifest.entrypoint` or `trial.expected`, so a match run entirely
through it can never trip a victory condition. That's expected — real
pass/fail signal requires both real agent execution (AAASM-4374/4375) and
real agent-assembly decisions (AAASM-4377), neither of which exists yet.
"""

from __future__ import annotations

import time
from pathlib import Path

from arena.models.manifest import AgentManifest
from arena.models.scenario import TrialSpec
from arena.runner.base import AgentRunResult


class NoOpRunner:
    """Always "succeeds" without launching an agent process or container."""

    def run(
        self,
        manifest: AgentManifest,
        trial: TrialSpec,
        *,
        workspace: Path,
    ) -> AgentRunResult:
        started = time.monotonic()
        workspace.mkdir(parents=True, exist_ok=True)
        duration = time.monotonic() - started
        return AgentRunResult(
            exit_code=0,
            stdout=f"[noop] {manifest.id} would run trial {trial.id!r}\n",
            stderr="",
            duration_seconds=duration,
        )
