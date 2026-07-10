"""AAASM-4386 end-to-end proof: the real `release-agent` official agent,
launched by the real `ProcessRunner`, produces stdout containing real
`ARENA_ACTION_ATTEMPT` markers, and — critically — the `tool` value it emits
for the `release-publish-requires-approval` trial matches that trial's
`expected` key *exactly*, as loaded from the real `TrialSpec` YAML (not a
hardcoded copy of it in this test). That equality is what ties "what this
agent attempts" to "what agent-assembly is expected to decide" (`ask`), per
AAASM-4386's acceptance criteria.

Deliberately invokes the agent's script directly via `sys.executable` plus
its **absolute** path, rather than through `agent.yaml`'s own
`entrypoint.command` (which uses a `../../../../`-relative offset assuming
the trial workspace is nested exactly 4 directories under the repo root —
see the "Working directory" section of `arena.runner.process`'s module
docstring, and `tests/test_integrations_official_agent_e2e.py` for the same
convention applied to `raw-python-issue-triager`). Using an absolute path
lets this test use a hermetic `tmp_path` workspace instead of writing into
the real repo tree.
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
from arena.models.scenario import Decision
from arena.runner.process import ProcessRunner
from arena.scenarios.loader import load_scenario_registry

REPO_ROOT = Path(__file__).resolve().parent.parent
REAL_SCENARIOS_ROOT = REPO_ROOT / "scenarios"
REAL_MAIN_PY = REPO_ROOT / "agents" / "official" / "release-agent" / "main.py"

_RELEASE_PUBLISH_TRIAL_ID = "release-publish-requires-approval"


def _release_agent_manifest() -> AgentManifest:
    command = f"{shlex.quote(sys.executable)} {shlex.quote(str(REAL_MAIN_PY))}"
    return AgentManifest(
        id="release-agent",
        name="Release Agent",
        framework="raw-python",
        entrypoint=AgentEntrypoint(type=EntrypointType.COMMAND, command=command),
        runtime=AgentRuntime(type=RuntimeType.PROCESS),
        scenarios=["github-maintainer-dungeon"],
    )


def test_release_agent_emits_one_parseable_action_attempt_per_trial(tmp_path: Path) -> None:
    """Every trial gets exactly one well-formed `ARENA_ACTION_ATTEMPT` marker."""
    bundle = load_scenario_registry(REAL_SCENARIOS_ROOT).get("github-maintainer-dungeon")
    assert bundle is not None
    manifest = _release_agent_manifest()
    runner = ProcessRunner()

    for trial in bundle.trials:
        workspace = tmp_path / trial.id
        result = runner.run(manifest, trial, workspace=workspace)

        assert result.exit_code == 0, result.stderr

        parsed = parse_action_attempts(result.stdout)

        assert parsed.errors == ()
        assert len(parsed.attempts) == 1
        attempt = parsed.attempts[0]
        assert attempt.agent_id == "release-agent"
        assert attempt.framework == "raw-python"
        assert attempt.scenario_id == "github-maintainer-dungeon"
        assert attempt.trial_id == trial.id
        assert attempt.resource
        assert attempt.context


def test_release_publish_action_matches_trial_expected_key_and_requires_approval(
    tmp_path: Path,
) -> None:
    """The AC this whole agent exists for: the high-risk action's `tool`
    value must equal the real trial spec's `expected` key exactly, and that
    key's expected `Decision` must be `ask` — not `allow`, not `deny`.
    """
    bundle = load_scenario_registry(REAL_SCENARIOS_ROOT).get("github-maintainer-dungeon")
    assert bundle is not None
    trial = next(t for t in bundle.trials if t.id == _RELEASE_PUBLISH_TRIAL_ID)

    manifest = _release_agent_manifest()
    runner = ProcessRunner()
    workspace = tmp_path / trial.id
    result = runner.run(manifest, trial, workspace=workspace)
    assert result.exit_code == 0, result.stderr

    parsed = parse_action_attempts(result.stdout)
    assert parsed.errors == ()
    assert len(parsed.attempts) == 1
    attempt = parsed.attempts[0]

    # The load-bearing assertion: the emitted tool is a key this trial
    # actually expects a decision for — not a hardcoded copy of the tool
    # name in this test, but the real `TrialSpec.expected` dict loaded from
    # `scenarios/github-maintainer-dungeon/trials/
    # release-publish-requires-approval.yaml`.
    assert attempt.tool in trial.expected
    assert trial.expected[attempt.tool] is Decision.ASK
