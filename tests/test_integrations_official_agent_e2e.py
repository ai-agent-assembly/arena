"""AAASM-4379 end-to-end proof: the real `raw-python-issue-triager` official
agent, launched by the real `ProcessRunner`, produces stdout containing real
`ARENA_ACTION_ATTEMPT` markers that `parse_action_attempts` can recover into
valid `ArenaActionAttempt` instances.

This exercises the actual `main.py` under `agents/official/
raw-python-issue-triager/` (updated by this ticket to call
`emit_action_attempt`) against the real `github-maintainer-dungeon` trial
specs — not a synthetic fixture — so the mechanism is proven against the one
real agent that exists today, not just in isolation.

Deliberately invokes the agent's script directly via `sys.executable` plus
its **absolute** path, rather than through `agent.yaml`'s own
`entrypoint.command` (which uses a `../../../../`-relative offset assuming
the trial workspace is nested exactly 4 directories under the repo root —
see the "Working directory" section of `arena.runner.process`'s module
docstring, and `test_run_github_maintainer_dungeon_smoke_with_official_agent`
in `tests/test_cli_run.py` for the full explanation of that limitation).
Using an absolute path lets this test use a hermetic `tmp_path` workspace
instead of writing into the real repo tree, matching the existing
`test_smoke_local_run.py` / `test_runner_process.py` convention.
"""

from __future__ import annotations

import shlex
import sys
from pathlib import Path

from arena.integrations.parser import parse_action_attempts
from arena.models.manifest import (
    AgentEntrypoint,
    AgentManifest,
    AgentRuntime,
    EntrypointType,
    RuntimeType,
)
from arena.runner.process import ProcessRunner
from arena.scenarios.loader import load_scenario_registry

REPO_ROOT = Path(__file__).resolve().parent.parent
REAL_SCENARIOS_ROOT = REPO_ROOT / "scenarios"
REAL_MAIN_PY = REPO_ROOT / "agents" / "official" / "raw-python-issue-triager" / "main.py"

#: tool this ticket's `_TRIAL_ACTIONS` mapping in the real agent's `main.py`
#: attaches to each real `github-maintainer-dungeon` trial id.
_EXPECTED_TOOL_BY_TRIAL = {
    "issue-triage-happy-path": "github.issues.comment",
    "prompt-injection-code-write": "github.contents.write",
    "secret-leak-attempt": "secrets.read",
    "release-publish-requires-approval": "github.releases.publish",
    "destructive-command-drop": "shell.exec",
}


def _official_agent_manifest() -> AgentManifest:
    command = f"{shlex.quote(sys.executable)} {shlex.quote(str(REAL_MAIN_PY))}"
    return AgentManifest(
        id="raw-python-issue-triager",
        name="Raw Python Issue Triage Agent",
        framework="raw-python",
        entrypoint=AgentEntrypoint(type=EntrypointType.COMMAND, command=command),
        runtime=AgentRuntime(type=RuntimeType.PROCESS),
        scenarios=["github-maintainer-dungeon"],
    )


def test_real_official_agent_emits_parseable_action_attempts(tmp_path: Path) -> None:
    bundle = load_scenario_registry(REAL_SCENARIOS_ROOT).get("github-maintainer-dungeon")
    assert bundle is not None
    manifest = _official_agent_manifest()
    runner = ProcessRunner()

    assert {trial.id for trial in bundle.trials} == set(_EXPECTED_TOOL_BY_TRIAL)

    for trial in bundle.trials:
        workspace = tmp_path / trial.id
        result = runner.run(manifest, trial, workspace=workspace)

        assert result.exit_code == 0, result.stderr

        parsed = parse_action_attempts(result.stdout)

        assert parsed.errors == ()
        assert len(parsed.attempts) == 1
        attempt = parsed.attempts[0]
        assert attempt.agent_id == "raw-python-issue-triager"
        assert attempt.framework == "raw-python"
        assert attempt.scenario_id == "github-maintainer-dungeon"
        assert attempt.trial_id == trial.id
        assert attempt.tool == _EXPECTED_TOOL_BY_TRIAL[trial.id]
        assert attempt.resource
        assert attempt.context
