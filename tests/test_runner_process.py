"""Unit tests for `ProcessRunner`, the real `EntrypointType.COMMAND` execution
backend (AAASM-4374).

These tests spawn genuine subprocesses via small script fixtures under
`tests/fixtures/process_runner/` rather than mocking `subprocess` — the
point of `ProcessRunner` is that it actually launches a process, and a mock
would only prove the mock was called correctly, not that capture/timeout/
failure handling behave correctly against a real OS process.
"""

from __future__ import annotations

import shlex
import sys
from pathlib import Path

import pytest

from arena.models.manifest import (
    AgentEntrypoint,
    AgentManifest,
    AgentRuntime,
    EntrypointType,
    RuntimeType,
)
from arena.models.scenario import Decision, Severity, TrialSpec
from arena.runner.base import Runner
from arena.runner.process import ProcessRunner

FIXTURES_DIR = Path(__file__).parent / "fixtures" / "process_runner"
ECHO_CONTEXT_SCRIPT = FIXTURES_DIR / "echo_context.py"
SLEEP_FOREVER_SCRIPT = FIXTURES_DIR / "sleep_forever.py"
ECHO_ENV_PROBE_SCRIPT = FIXTURES_DIR / "echo_env_probe.py"

_TRIAL = TrialSpec(
    id="example-trial",
    description="A trial used only to exercise ProcessRunner.",
    expected={"some.action": Decision.ALLOW},
    severity=Severity.HIGH,
)


def _manifest(command: str, *, env: dict[str, str] | None = None) -> AgentManifest:
    return AgentManifest(
        id="process-test-agent",
        name="Process Test Agent",
        framework="raw-python",
        entrypoint=AgentEntrypoint(type=EntrypointType.COMMAND, command=command, env=env or {}),
        runtime=AgentRuntime(type=RuntimeType.PROCESS),
        scenarios=["example-scenario"],
    )


def _echo_context_command(exit_code: int = 0) -> str:
    return f"{shlex.quote(sys.executable)} {shlex.quote(str(ECHO_CONTEXT_SCRIPT))} {exit_code}"


def test_process_runner_satisfies_runner_protocol() -> None:
    assert isinstance(ProcessRunner(), Runner)


def test_process_runner_captures_stdout_stderr_and_exit_code(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"

    result = ProcessRunner().run(_manifest(_echo_context_command(3)), _TRIAL, workspace=workspace)

    assert result.exit_code == 3
    assert "this went to stderr" in result.stderr
    assert result.duration_seconds >= 0.0
    assert workspace.is_dir()


def test_process_runner_passes_trial_and_agent_context_via_env(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"

    result = ProcessRunner().run(_manifest(_echo_context_command()), _TRIAL, workspace=workspace)

    assert result.exit_code == 0
    assert "agent_id=process-test-agent" in result.stdout
    assert "trial_id=example-trial" in result.stdout
    assert "trial_description=A trial used only to exercise ProcessRunner." in result.stdout
    assert "trial_severity=high" in result.stdout
    assert f"workspace={workspace}" in result.stdout


def test_process_runner_merges_manifest_declared_env(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    manifest = _manifest(_echo_context_command(), env={"FIXTURE_MANIFEST_ENV": "from-manifest"})

    result = ProcessRunner().run(manifest, _TRIAL, workspace=workspace)

    assert result.exit_code == 0
    assert "manifest_env=from-manifest" in result.stdout


def test_process_runner_does_not_leak_unlisted_host_env(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # A secret planted in Arena's own environment (the kind of CI/repo
    # credential DockerRunner deliberately withholds) must not be inherited by
    # the agent subprocess, while an allowlisted base var (PATH) still is — see
    # `arena.runner.process._SAFE_BASE_ENV_VARS`.
    workspace = tmp_path / "workspace"
    monkeypatch.setenv("AASM_TEST_HOST_SECRET", "super-secret-token")
    command = f"{shlex.quote(sys.executable)} {shlex.quote(str(ECHO_ENV_PROBE_SCRIPT))}"

    result = ProcessRunner().run(_manifest(command), _TRIAL, workspace=workspace)

    assert result.exit_code == 0
    assert "host_secret=ABSENT" in result.stdout
    assert "super-secret-token" not in result.stdout
    assert "path=set" in result.stdout


def test_process_runner_enforces_timeout_without_raising(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    command = f"{shlex.quote(sys.executable)} {shlex.quote(str(SLEEP_FOREVER_SCRIPT))}"
    manifest = _manifest(command)
    runner = ProcessRunner(timeout_seconds=0.5)

    result = runner.run(manifest, _TRIAL, workspace=workspace)

    assert result.exit_code != 0
    assert "timed out" in result.stderr
    assert "0.5" in result.stderr
    # A generous upper bound so this stays reliable under CI load, while
    # still proving the runner didn't just wait out the 60s sleep.
    assert result.duration_seconds < 30.0


def test_process_runner_nonexistent_command_does_not_raise(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    manifest = _manifest("arena-test-definitely-not-a-real-command-xyz")

    result = ProcessRunner().run(manifest, _TRIAL, workspace=workspace)

    assert result.exit_code != 0
    assert "failed to launch" in result.stderr
    assert "arena-test-definitely-not-a-real-command-xyz" in result.stderr
    assert result.stdout == ""
