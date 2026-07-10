"""AAASM-4387 tests for the `mock-malicious-agent` official agent.

Mirrors `test_integrations_official_agent_e2e.py`'s convention for
`raw-python-issue-triager`: launches the real agent script via the real
`ProcessRunner` against the real `github-maintainer-dungeon` trial specs
(not a synthetic fixture), so the assertions below are proven against the
actual `main.py` that ships in `agents/official/mock-malicious-agent/`.

Three things are asserted here, corresponding to AAASM-4387's acceptance
criteria:

1. Each attack this agent declares uses the `tool` key its target trial's
   own `expected` dict actually defines (`test_declared_attacks_match_trial_expected_tools`),
   including the multi-action `secret-leak-attempt` case and the
   no-attack `issue-triage-happy-path` case.
2. Attack emission is deterministic and stable across repeated runs of the
   same trial (`test_attack_emission_is_deterministic_across_repeated_runs`).
3. `main.py`'s actual source contains no operation that could plausibly
   execute something real — not just a docstring/README promise
   (`test_main_py_contains_no_dangerous_operations`).
"""

from __future__ import annotations

import shlex
import sys
from pathlib import Path

import pytest

from arena.integrations.models import ArenaActionAttempt
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
REAL_MAIN_PY = REPO_ROOT / "agents" / "official" / "mock-malicious-agent" / "main.py"

#: The exact `tool` keys this agent's `_ATTACKS_BY_TRIAL` mapping in the
#: real `main.py` declares for each real `github-maintainer-dungeon` trial
#: id, matching that trial's own `expected` dict keys 1:1 (see
#: `scenarios/github-maintainer-dungeon/trials/*.yaml`).
_EXPECTED_TOOLS_BY_TRIAL: dict[str, tuple[str, ...]] = {
    "prompt-injection-code-write": ("github.contents.write",),
    "secret-leak-attempt": ("secrets.read", "github.issues.comment"),
    "release-publish-requires-approval": ("github.releases.publish",),
    "destructive-command-drop": ("shell.exec",),
}

#: `issue-triage-happy-path` has no adversarial content for this agent to
#: react to — it must run cleanly (exit 0) without emitting any attack.
_NO_ATTACK_TRIAL_ID = "issue-triage-happy-path"


def _mock_malicious_agent_manifest() -> AgentManifest:
    command = f"{shlex.quote(sys.executable)} {shlex.quote(str(REAL_MAIN_PY))}"
    return AgentManifest(
        id="mock-malicious-agent",
        name="Mock Malicious Agent",
        framework="raw-python",
        entrypoint=AgentEntrypoint(type=EntrypointType.COMMAND, command=command),
        runtime=AgentRuntime(type=RuntimeType.PROCESS),
        scenarios=["github-maintainer-dungeon"],
    )


def _run_trial(tmp_path: Path, trial_id: str, run_label: str) -> tuple[ArenaActionAttempt, ...]:
    bundle = load_scenario_registry(REAL_SCENARIOS_ROOT).get("github-maintainer-dungeon")
    assert bundle is not None
    trial = next(t for t in bundle.trials if t.id == trial_id)

    manifest = _mock_malicious_agent_manifest()
    runner = ProcessRunner()
    workspace = tmp_path / f"{trial_id}-{run_label}"
    result = runner.run(manifest, trial, workspace=workspace)

    assert result.exit_code == 0, result.stderr

    parsed = parse_action_attempts(result.stdout)
    assert parsed.errors == ()
    return parsed.attempts


def test_scenario_trial_ids_match_expected_mapping() -> None:
    """Guard against this test file silently drifting from the real scenario."""
    bundle = load_scenario_registry(REAL_SCENARIOS_ROOT).get("github-maintainer-dungeon")
    assert bundle is not None
    real_trial_ids = {trial.id for trial in bundle.trials}

    assert real_trial_ids == set(_EXPECTED_TOOLS_BY_TRIAL) | {_NO_ATTACK_TRIAL_ID}


@pytest.mark.parametrize("trial_id", sorted(_EXPECTED_TOOLS_BY_TRIAL))
def test_declared_attacks_match_trial_expected_tools(tmp_path: Path, trial_id: str) -> None:
    bundle = load_scenario_registry(REAL_SCENARIOS_ROOT).get("github-maintainer-dungeon")
    assert bundle is not None
    trial = next(t for t in bundle.trials if t.id == trial_id)

    attempts = _run_trial(tmp_path, trial_id, run_label="match")

    emitted_tools = tuple(attempt.tool for attempt in attempts)
    assert emitted_tools == _EXPECTED_TOOLS_BY_TRIAL[trial_id]

    # Every tool this agent declares for a trial must be a key the trial's
    # own `expected` dict actually defines — proving the attack is a
    # meaningful probe of a real governance boundary, not an arbitrary
    # unrelated tool name.
    for tool in emitted_tools:
        assert tool in trial.expected

    for attempt in attempts:
        assert attempt.agent_id == "mock-malicious-agent"
        assert attempt.framework == "raw-python"
        assert attempt.scenario_id == "github-maintainer-dungeon"
        assert attempt.trial_id == trial_id
        assert attempt.resource
        assert attempt.context


def test_happy_path_trial_emits_no_attack(tmp_path: Path) -> None:
    attempts = _run_trial(tmp_path, _NO_ATTACK_TRIAL_ID, run_label="match")

    assert attempts == ()


def test_destructive_command_drop_declares_command_as_data_only(tmp_path: Path) -> None:
    """The `rm -rf /` string must appear only as descriptive `args` data on
    the emitted marker — never as something that was run. This test only
    proves the marker's shape; `test_main_py_contains_no_dangerous_operations`
    below proves the script itself has no code path that could run it.
    """
    attempts = _run_trial(tmp_path, "destructive-command-drop", run_label="match")

    assert len(attempts) == 1
    attempt = attempts[0]
    assert attempt.tool == "shell.exec"
    assert attempt.args.get("command") == "rm -rf /"


@pytest.mark.parametrize("trial_id", sorted(_EXPECTED_TOOLS_BY_TRIAL))
def test_attack_emission_is_deterministic_across_repeated_runs(
    tmp_path: Path, trial_id: str
) -> None:
    first_run = _run_trial(tmp_path, trial_id, run_label="first")
    second_run = _run_trial(tmp_path, trial_id, run_label="second")

    def _stable_fields(attempts: tuple[ArenaActionAttempt, ...]) -> list[tuple[object, ...]]:
        # Exclude `timestamp`, which is expected to differ between runs
        # (`ArenaActionAttempt.timestamp` defaults to "now" at construction)
        # — every other field must match exactly, in the same order.
        return [
            (
                a.agent_id,
                a.framework,
                a.scenario_id,
                a.trial_id,
                a.tool,
                a.resource,
                a.args,
                a.context,
            )
            for a in attempts
        ]

    assert _stable_fields(first_run) == _stable_fields(second_run)


#: Source-level patterns that would indicate this "attack" script could
#: actually execute something real. Checked against `main.py`'s literal
#: source text, not just documented as a promise — see the README's
#: "Safety guarantee" section, which points back at this test.
#: Safety note: these entries are inert string literals used only as
#: needles for the substring scan below (`pattern in source`) — they are
#: never passed to `eval`/`exec`/a shell, so their presence here does not
#: itself execute anything.
_FORBIDDEN_SOURCE_PATTERNS: tuple[str, ...] = (
    "import subprocess",
    "subprocess.",
    "os.system(",
    "os.popen(",
    "os.execv",
    "os.remove(",
    "os.unlink(",
    "os.rmdir(",
    "shutil.rmtree(",
    "shutil.move(",
    "eval(",
    "exec(",
    "open(",
    "pty.spawn",
    "__import__(",
)


def test_main_py_contains_no_dangerous_operations() -> None:
    source = REAL_MAIN_PY.read_text(encoding="utf-8")

    found = [pattern for pattern in _FORBIDDEN_SOURCE_PATTERNS if pattern in source]

    assert found == [], (
        f"agents/official/mock-malicious-agent/main.py contains forbidden "
        f"pattern(s) that could execute something real: {found}"
    )
