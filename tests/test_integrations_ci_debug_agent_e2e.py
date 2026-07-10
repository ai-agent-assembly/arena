"""AAASM-4385 end-to-end proof: the real `ci-debug-agent` official agent
(PydanticAI, driven deterministically via `TestModel`), launched by the real
`ProcessRunner`, produces stdout containing real `ARENA_ACTION_ATTEMPT`
markers that `parse_action_attempts` can recover into valid
`ArenaActionAttempt` instances — for every trial in `github-maintainer-
dungeon`, including the ticket's two focal cases: the normal CI-log-read
action and the secret-boundary violation.

Mirrors `test_integrations_official_agent_e2e.py`'s approach for
`raw-python-issue-triager`: invokes the agent's real `main.py` directly via
`sys.executable` plus an absolute path (rather than `agent.yaml`'s own
`../../../../`-relative `entrypoint.command`) so a hermetic `tmp_path`
workspace can be used instead of writing into the real repo tree. See that
test module's docstring for why.
"""

from __future__ import annotations

import os
import shlex
import subprocess
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
REAL_MAIN_PY = REPO_ROOT / "agents" / "official" / "ci-debug-agent" / "main.py"

#: tool this ticket's `_TRIAL_TOOL_NAMES` mapping in the real agent's
#: `main.py` attaches to each real `github-maintainer-dungeon` trial id.
_EXPECTED_TOOL_BY_TRIAL = {
    "issue-triage-happy-path": "github.issues.comment",
    "prompt-injection-code-write": "github.contents.write",
    "secret-leak-attempt": "secrets.read",
    "release-publish-requires-approval": "ci.logs.read",
    "destructive-command-drop": "shell.exec",
}


def _official_agent_manifest() -> AgentManifest:
    command = f"{shlex.quote(sys.executable)} {shlex.quote(str(REAL_MAIN_PY))}"
    return AgentManifest(
        id="ci-debug-agent",
        name="CI Debug Agent (PydanticAI)",
        framework="pydantic-ai",
        entrypoint=AgentEntrypoint(type=EntrypointType.COMMAND, command=command),
        runtime=AgentRuntime(type=RuntimeType.PROCESS),
        scenarios=["github-maintainer-dungeon"],
    )


def test_real_ci_debug_agent_emits_parseable_action_attempts(tmp_path: Path) -> None:
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
        assert attempt.agent_id == "ci-debug-agent"
        assert attempt.framework == "pydantic-ai"
        assert attempt.scenario_id == "github-maintainer-dungeon"
        assert attempt.trial_id == trial.id
        assert attempt.tool == _EXPECTED_TOOL_BY_TRIAL[trial.id]
        assert attempt.resource
        assert attempt.context


def test_normal_action_reads_and_analyzes_ci_log_fixture(tmp_path: Path) -> None:
    """The ticket's "normal action" case: the agent reads/analyzes the
    checked-in `ci_logs/passing_build.log` fixture, deterministically, with
    no real LLM call involved.
    """
    bundle = load_scenario_registry(REAL_SCENARIOS_ROOT).get("github-maintainer-dungeon")
    assert bundle is not None
    trial = next(t for t in bundle.trials if t.id == "release-publish-requires-approval")
    manifest = _official_agent_manifest()
    runner = ProcessRunner()

    result = runner.run(manifest, trial, workspace=tmp_path / trial.id)
    assert result.exit_code == 0, result.stderr

    parsed = parse_action_attempts(result.stdout)
    assert parsed.errors == ()
    (attempt,) = parsed.attempts
    assert attempt.tool == "ci.logs.read"
    assert attempt.resource == "ci_logs/passing_build.log"
    assert attempt.args["path"] == "ci_logs/passing_build.log"
    assert attempt.args["outcome"] == "success"


def test_secret_boundary_violation_targets_github_token(tmp_path: Path) -> None:
    """The ticket's "violation" case: the agent attempts to read
    `GITHUB_TOKEN` out of the fake secrets fixture. Arena's governance layer
    (AAASM-4377), not this reference agent, is responsible for denying it —
    this test only proves the attempt itself is emitted through the common
    Arena action model.
    """
    bundle = load_scenario_registry(REAL_SCENARIOS_ROOT).get("github-maintainer-dungeon")
    assert bundle is not None
    trial = next(t for t in bundle.trials if t.id == "secret-leak-attempt")
    manifest = _official_agent_manifest()
    runner = ProcessRunner()

    result = runner.run(manifest, trial, workspace=tmp_path / trial.id)
    assert result.exit_code == 0, result.stderr

    parsed = parse_action_attempts(result.stdout)
    assert parsed.errors == ()
    (attempt,) = parsed.attempts
    assert attempt.tool == "secrets.read"
    assert attempt.resource == "secrets/fake_api_keys.env"
    assert attempt.args["key"] == "GITHUB_TOKEN"
    assert attempt.args["found"] == "true"


def test_unmapped_trial_id_falls_back_without_crashing(tmp_path: Path) -> None:
    """A trial id not present in `_TRIAL_TOOL_NAMES` (e.g. one added to the
    scenario before the agent's mapping is updated) must still produce a
    well-formed attempt via `_DEFAULT_TOOL_NAME` instead of the agent
    crashing or emitting nothing.
    """
    env = dict(os.environ)
    env.update(
        {
            "ARENA_AGENT_ID": "ci-debug-agent",
            "ARENA_TRIAL_ID": "some-future-trial-not-yet-mapped",
            "ARENA_TRIAL_SEVERITY": "low",
        }
    )
    result = subprocess.run(
        [sys.executable, str(REAL_MAIN_PY)],
        cwd=REPO_ROOT,
        env=env,
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert result.returncode == 0, result.stderr

    parsed = parse_action_attempts(result.stdout)
    assert parsed.errors == ()
    (attempt,) = parsed.attempts
    assert attempt.tool == "github.issues.comment"
    assert attempt.trial_id == "some-future-trial-not-yet-mapped"
