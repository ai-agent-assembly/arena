"""Entrypoint for the `raw-python-issue-triager` official agent.

A deliberately minimal, "naive" reference agent for the
`github-maintainer-dungeon` scenario (AAASM-4368): it reads the per-trial
context `ProcessRunner` passes via environment variables (see
`arena.runner.process._build_env` for the exact names/semantics —
`ARENA_AGENT_ID`, `ARENA_TRIAL_ID`, `ARENA_TRIAL_DESCRIPTION`,
`ARENA_TRIAL_SEVERITY`, `ARENA_WORKSPACE`) and prints an acknowledgement of
the trial it's handling, the way a real maintainer-bot might log before
acting.

It does not call the GitHub API and implements no real triage intelligence
or governance logic — that is deliberately not this script's job. This
agent exits `0` unconditionally, including for the scenario's adversarial
trials (prompt-injection, secret-leak, release-publish, destructive-command):
it represents a naive maintainer bot that would happily comply with
whatever an issue or CI event asks unless something else stops it, so that
agent-assembly's own governance layer is what gets exercised as the actual
defender once AAASM-4377 wires in real decisions — not this script
pre-empting a verdict it has no way to know. See `docs/local-execution.md`
for why "every trial currently shows PASS" is an artifact of the interim
`TrialOutcome.passed` proxy (`exit_code == 0`), not a real governance
verdict, until AAASM-4377 lands.
"""

from __future__ import annotations

import os


def main() -> None:
    agent_id = os.environ.get("ARENA_AGENT_ID", "raw-python-issue-triager")
    trial_id = os.environ.get("ARENA_TRIAL_ID", "<unknown-trial>")
    description = os.environ.get("ARENA_TRIAL_DESCRIPTION", "")
    severity = os.environ.get("ARENA_TRIAL_SEVERITY", "<unknown-severity>")
    workspace = os.environ.get("ARENA_WORKSPACE", "")

    print(f"[{agent_id}] handling trial {trial_id!r} (severity={severity})")
    if description:
        print(f"  context: {description}")
    if workspace:
        print(f"  workspace: {workspace}")
    print(f"[{agent_id}] triage complete for {trial_id!r}")


if __name__ == "__main__":
    main()
