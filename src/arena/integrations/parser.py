"""Parse-side: recover `ArenaActionAttempt`s from an agent process's raw
captured stdout.

`AgentRunResult.stdout` (AAASM-4373/4374) holds an agent's entire captured
stdout as one string, mixed in with whatever else the agent printed. This
module scans that text line by line for
`arena.integrations.emit.ACTION_ATTEMPT_MARKER_PREFIX`-prefixed lines and
validates each one back into a real `ArenaActionAttempt`.

Malformed markers (invalid JSON, or JSON that fails `ArenaActionAttempt`
validation — e.g. a hand-crafted or truncated marker from a misbehaving
agent) are recorded as errors and skipped rather than raising: one broken
marker line must not prevent every other real attempt in the same output
from being recovered, mirroring `ProcessRunner`'s own "one broken agent
process cannot crash the rest of a match" contract
(`arena.runner.process`).

Nothing in this module is wired into match orchestration yet. Turning
captured stdout into audit/report data as part of a live match run is
AAASM-4380's job (it owns audit/decision capture) — this module is the
library function it calls to do so.
"""

from __future__ import annotations

import json
from dataclasses import dataclass

from pydantic import ValidationError

from arena.integrations.emit import ACTION_ATTEMPT_MARKER_PREFIX
from arena.integrations.models import ArenaActionAttempt


@dataclass(frozen=True)
class ActionAttemptParseResult:
    """The outcome of scanning one blob of captured stdout for markers.

    `errors` holds one human-readable message per malformed marker line
    found (1-indexed line number plus what went wrong), so a caller can
    surface or log them without the parse itself raising.
    """

    attempts: tuple[ArenaActionAttempt, ...]
    errors: tuple[str, ...]


def parse_action_attempts(stdout: str) -> ActionAttemptParseResult:
    """Extract every `ArenaActionAttempt` marker line from captured stdout.

    Lines that don't start with `ACTION_ATTEMPT_MARKER_PREFIX` are ordinary
    agent output and are silently ignored — only marker lines are
    considered at all, so an agent's normal logging (or a framework's own
    stdout chatter) never triggers a spurious error entry.
    """
    attempts: list[ArenaActionAttempt] = []
    errors: list[str] = []

    for line_number, raw_line in enumerate(stdout.splitlines(), start=1):
        line = raw_line.strip()
        if not line.startswith(ACTION_ATTEMPT_MARKER_PREFIX):
            continue

        payload = line[len(ACTION_ATTEMPT_MARKER_PREFIX) :]
        try:
            data = json.loads(payload)
        except json.JSONDecodeError as exc:
            errors.append(f"line {line_number}: invalid JSON in action-attempt marker: {exc}")
            continue

        try:
            attempts.append(ArenaActionAttempt.model_validate(data))
        except ValidationError as exc:
            errors.append(f"line {line_number}: invalid ArenaActionAttempt payload: {exc}")
            continue

    return ActionAttemptParseResult(attempts=tuple(attempts), errors=tuple(errors))
