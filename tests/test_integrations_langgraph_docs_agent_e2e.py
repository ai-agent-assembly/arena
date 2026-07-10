"""AAASM-4384 end-to-end proof: the real `langgraph-docs-agent` official
agent — a genuine LangGraph `StateGraph`, launched by the real
`ProcessRunner` — produces stdout containing real `ARENA_ACTION_ATTEMPT`
markers that `parse_action_attempts` can recover into valid
`ArenaActionAttempt` instances, and its committed manifest validates via the
real `arena.agents.loader.load_manifest`.

Mirrors `tests/test_integrations_official_agent_e2e.py`'s approach for
`raw-python-issue-triager`: invokes the agent's script directly via
`sys.executable` plus its **absolute** path (rather than through
`agent.yaml`'s own `../../../../`-relative `entrypoint.command`, which
assumes a trial workspace nested exactly 4 directories under the repo
root — see that file's docstring for the full explanation), so this test
can use a hermetic `tmp_path` workspace instead of writing into the real
repo tree.
"""

from __future__ import annotations

import shlex
import sys
from pathlib import Path

from arena.agents.loader import load_manifest
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
REAL_AGENT_DIR = REPO_ROOT / "agents" / "official" / "langgraph-docs-agent"
REAL_MAIN_PY = REAL_AGENT_DIR / "main.py"
REAL_MANIFEST_PATH = REAL_AGENT_DIR / "agent.yaml"

#: The tool this agent's `_TRIAL_ACTIONS` mapping in `main.py` attaches to
#: each real `github-maintainer-dungeon` trial id — see that module's
#: docstring "Trial → behavior mapping" section for the reasoning.
_EXPECTED_TOOL_BY_TRIAL = {
    "issue-triage-happy-path": "docs.write",
    "prompt-injection-code-write": "fs.write",
    "secret-leak-attempt": "fs.read",
    "release-publish-requires-approval": "docs.write",
    "destructive-command-drop": "docs.write",
}

#: Trials that represent a resource/data boundary violation per this
#: agent's mapping — used below to assert their resource actually falls
#: outside `docs/**`, the agent's declared normal scope.
_BOUNDARY_VIOLATION_TRIALS = {"prompt-injection-code-write", "secret-leak-attempt"}


def _official_agent_manifest() -> AgentManifest:
    command = f"{shlex.quote(sys.executable)} {shlex.quote(str(REAL_MAIN_PY))}"
    return AgentManifest(
        id="langgraph-docs-agent",
        name="LangGraph Docs Agent",
        framework="langgraph",
        entrypoint=AgentEntrypoint(type=EntrypointType.COMMAND, command=command),
        runtime=AgentRuntime(type=RuntimeType.PROCESS),
        scenarios=["github-maintainer-dungeon"],
    )


def test_committed_manifest_validates() -> None:
    manifest = load_manifest(REAL_MANIFEST_PATH)

    assert manifest.id == "langgraph-docs-agent"
    assert manifest.framework == "langgraph"
    assert manifest.scenarios == ["github-maintainer-dungeon"]


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
        assert attempt.agent_id == "langgraph-docs-agent"
        assert attempt.framework == "langgraph"
        assert attempt.scenario_id == "github-maintainer-dungeon"
        assert attempt.trial_id == trial.id
        assert attempt.tool == _EXPECTED_TOOL_BY_TRIAL[trial.id]
        assert attempt.resource
        assert attempt.context

        if trial.id in _BOUNDARY_VIOLATION_TRIALS:
            assert not attempt.resource.startswith("docs/")
        else:
            assert attempt.resource.startswith("docs/")
