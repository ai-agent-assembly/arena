"""Emit-side helper: lets an agent process signal "I attempted this action"
to Arena without needing any IPC channel back into Arena's own process.

**Design rationale.** Agent plugins run as separate OS processes
(`ProcessRunner`) or containers (`DockerRunner`) — they are not Python
objects living inside Arena's process, so there is no in-memory call Arena
can make into an agent to ask "what did you attempt?" `AgentRunResult`
(AAASM-4373/4374) already captures an agent's entire stdout verbatim, so the
mechanism here is: print one single-line, JSON-prefixed marker per attempted
action, and let a later parse step (`arena.integrations.parser`) recover it
from that captured output.

A stdout marker is framework-agnostic by construction — it doesn't care
what's happening inside the agent's process, only that the process can
print a line, which every framework can do regardless of its internal
tool-calling machinery. That's why this approach doesn't preclude
LangGraph/PydanticAI/CrewAI agents (AAASM-4382, not built yet): they need no
framework-specific integration here, just a call to `emit_action_attempt`
from wherever their own tool-call handling lives.

The marker is prefixed with `ACTION_ATTEMPT_MARKER_PREFIX` so it's
greppable/parseable from an agent's full captured stdout without clobbering
its other logging (diagnostic prints, framework log lines, etc. never
collide with it unless they happen to start with this exact prefix).
"""

from __future__ import annotations

import os
import sys
from typing import Any, TextIO

from arena.integrations.models import ArenaActionAttempt

#: Prefix marking a stdout line as a machine-readable action-attempt event.
#: `arena.integrations.parser.parse_action_attempts` scans captured stdout
#: for lines starting with this exact string.
ACTION_ATTEMPT_MARKER_PREFIX = "ARENA_ACTION_ATTEMPT: "


def emit_action_attempt(
    *,
    tool: str,
    resource: str,
    framework: str,
    scenario_id: str,
    args: dict[str, Any] | None = None,
    context: str | None = None,
    agent_id: str | None = None,
    trial_id: str | None = None,
    stream: TextIO = sys.stdout,
) -> ArenaActionAttempt:
    """Build an `ArenaActionAttempt` and print it as a marker line to `stream`.

    `agent_id`/`trial_id` default to the `ARENA_AGENT_ID`/`ARENA_TRIAL_ID`
    environment variables `ProcessRunner`/`DockerRunner` already set for
    every agent invocation (see `arena.runner.process._build_env`), so a
    typical call site only needs to name what it's attempting rather than
    restate context the runner already gave it.

    `framework`/`scenario_id` have no environment fallback — the runner does
    not pass either (`AgentManifest.scenarios` is a list, not a single
    active scenario, and `TrialSpec` carries no scenario id of its own, so
    there is no single unambiguous value `ProcessRunner`/`DockerRunner`
    could set). They're static facts about the calling agent itself, not
    per-run context, so a call site states them explicitly — typically as
    module-level constants matching the agent's own `agent.yaml`.

    Raises:
        ValueError: `agent_id`/`trial_id` was not given and the
            corresponding `ARENA_*` environment variable is unset — this
            happens if a script is invoked outside of `ProcessRunner`/
            `DockerRunner` (e.g. manual local testing) without supplying
            the ids explicitly.
    """
    resolved_agent_id = agent_id if agent_id is not None else os.environ.get("ARENA_AGENT_ID")
    resolved_trial_id = trial_id if trial_id is not None else os.environ.get("ARENA_TRIAL_ID")
    if not resolved_agent_id:
        raise ValueError("agent_id was not given and ARENA_AGENT_ID is not set in the environment")
    if not resolved_trial_id:
        raise ValueError("trial_id was not given and ARENA_TRIAL_ID is not set in the environment")

    attempt = ArenaActionAttempt(
        agent_id=resolved_agent_id,
        framework=framework,
        scenario_id=scenario_id,
        trial_id=resolved_trial_id,
        tool=tool,
        resource=resource,
        args=args or {},
        context=context,
    )
    print(f"{ACTION_ATTEMPT_MARKER_PREFIX}{attempt.model_dump_json()}", file=stream, flush=True)
    return attempt
