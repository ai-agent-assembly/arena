"""Unit tests for `DockerRunner` (`arena.runner.docker`).

No live Docker daemon is required or used here: every test injects a stub
`command_runner` in place of `subprocess.run` so behavior is asserted
against the constructed `docker run` argv and canned results, deterministically
and without a network/daemon dependency. See `docs/runners.md` for why the
test suite is built this way rather than against a live daemon.
"""

from __future__ import annotations

import subprocess
from pathlib import Path
from typing import Any

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
from arena.runner.docker import DockerRunner

_TRIAL = TrialSpec(
    id="example-trial",
    description="A trial used only to exercise DockerRunner.",
    expected={"some.action": Decision.ALLOW},
    severity=Severity.LOW,
)


def _docker_manifest(
    *, env: dict[str, str] | None = None, command: str | None = None
) -> AgentManifest:
    return AgentManifest(
        id="docker-test-agent",
        name="Docker Test Agent",
        framework="raw-python",
        entrypoint=AgentEntrypoint(
            type=EntrypointType.DOCKER,
            image="ghcr.io/example/agent:latest",
            env=env or {},
            command=command,
        ),
        runtime=AgentRuntime(type=RuntimeType.CONTAINER),
        scenarios=["example-scenario"],
    )


class _RecordingCommandRunner:
    """Stub in place of `subprocess.run`: records the argv/kwargs it was
    called with and returns (or raises) whatever the test configured.
    """

    def __init__(
        self,
        *,
        result: subprocess.CompletedProcess[str] | None = None,
        error: Exception | None = None,
    ) -> None:
        self._result = result
        self._error = error
        self.calls: list[tuple[list[str], dict[str, Any]]] = []

    def __call__(self, argv: list[str], **kwargs: Any) -> subprocess.CompletedProcess[str]:
        self.calls.append((argv, kwargs))
        if self._error is not None:
            raise self._error
        assert self._result is not None
        return self._result


def test_docker_runner_satisfies_runner_protocol() -> None:
    assert isinstance(DockerRunner(), Runner)


def test_docker_runner_invokes_docker_run_and_reports_result(tmp_path: Path) -> None:
    stub = _RecordingCommandRunner(
        result=subprocess.CompletedProcess(args=[], returncode=0, stdout="hello\n", stderr="")
    )
    runner = DockerRunner(command_runner=stub)

    result = runner.run(_docker_manifest(), _TRIAL, workspace=tmp_path / "ws")

    assert result.exit_code == 0
    assert result.stdout == "hello\n"
    assert result.stderr == ""
    assert result.duration_seconds >= 0.0
    assert len(stub.calls) == 1


def test_docker_runner_creates_workspace(tmp_path: Path) -> None:
    stub = _RecordingCommandRunner(
        result=subprocess.CompletedProcess(args=[], returncode=0, stdout="", stderr="")
    )
    workspace = tmp_path / "nested" / "ws"
    assert not workspace.exists()

    DockerRunner(command_runner=stub).run(_docker_manifest(), _TRIAL, workspace=workspace)

    assert workspace.is_dir()


def test_docker_run_argv_never_includes_privileged(tmp_path: Path) -> None:
    stub = _RecordingCommandRunner(
        result=subprocess.CompletedProcess(args=[], returncode=0, stdout="", stderr="")
    )
    DockerRunner(command_runner=stub).run(_docker_manifest(), _TRIAL, workspace=tmp_path / "ws")

    argv = stub.calls[0][0]
    assert "--privileged" not in argv


def test_docker_run_argv_sets_explicit_workdir(tmp_path: Path) -> None:
    stub = _RecordingCommandRunner(
        result=subprocess.CompletedProcess(args=[], returncode=0, stdout="", stderr="")
    )
    DockerRunner(command_runner=stub).run(_docker_manifest(), _TRIAL, workspace=tmp_path / "ws")

    argv = stub.calls[0][0]
    assert "--workdir" in argv
    workdir_index = argv.index("--workdir")
    assert argv[workdir_index + 1] == "/workspace"


def test_docker_run_argv_has_no_env_flags_by_default(tmp_path: Path) -> None:
    stub = _RecordingCommandRunner(
        result=subprocess.CompletedProcess(args=[], returncode=0, stdout="", stderr="")
    )
    DockerRunner(command_runner=stub).run(_docker_manifest(), _TRIAL, workspace=tmp_path / "ws")

    argv = stub.calls[0][0]
    assert "--env" not in argv
    assert "--env-file" not in argv


def test_docker_run_argv_only_passes_manifest_declared_env(tmp_path: Path) -> None:
    stub = _RecordingCommandRunner(
        result=subprocess.CompletedProcess(args=[], returncode=0, stdout="", stderr="")
    )
    manifest = _docker_manifest(env={"AGENT_MODE": "trial"})

    DockerRunner(command_runner=stub).run(manifest, _TRIAL, workspace=tmp_path / "ws")

    argv = stub.calls[0][0]
    assert argv.count("--env") == 1
    env_index = argv.index("--env")
    assert argv[env_index + 1] == "AGENT_MODE=trial"
    # No host-environment passthrough flag of any kind.
    assert "--env-file" not in argv
    assert not any(flag in argv for flag in ("--env-host", "-e-all"))


def test_docker_run_argv_uses_configured_timeout(tmp_path: Path) -> None:
    stub = _RecordingCommandRunner(
        result=subprocess.CompletedProcess(args=[], returncode=0, stdout="", stderr="")
    )
    runner = DockerRunner(command_runner=stub, timeout_seconds=5.0)

    runner.run(_docker_manifest(), _TRIAL, workspace=tmp_path / "ws")

    kwargs = stub.calls[0][1]
    assert kwargs["timeout"] == pytest.approx(5.0)


def test_docker_run_argv_includes_image_and_manifest_command_override(tmp_path: Path) -> None:
    stub = _RecordingCommandRunner(
        result=subprocess.CompletedProcess(args=[], returncode=0, stdout="", stderr="")
    )
    manifest = _docker_manifest(command="python main.py --trial")

    DockerRunner(command_runner=stub).run(manifest, _TRIAL, workspace=tmp_path / "ws")

    argv = stub.calls[0][0]
    assert "ghcr.io/example/agent:latest" in argv
    assert argv[-3:] == ["python", "main.py", "--trial"]


def test_docker_unavailable_returns_reportable_result_without_raising(tmp_path: Path) -> None:
    stub = _RecordingCommandRunner(error=FileNotFoundError("docker: command not found"))

    result = DockerRunner(command_runner=stub).run(
        _docker_manifest(), _TRIAL, workspace=tmp_path / "ws"
    )

    assert result.exit_code != 0
    assert "docker" in result.stderr.lower()


def test_container_launch_failure_returns_reportable_result_without_raising(tmp_path: Path) -> None:
    stub = _RecordingCommandRunner(error=PermissionError("Cannot connect to the Docker daemon"))

    result = DockerRunner(command_runner=stub).run(
        _docker_manifest(), _TRIAL, workspace=tmp_path / "ws"
    )

    assert result.exit_code != 0
    assert "docker daemon" in result.stderr.lower() or "failed to launch" in result.stderr.lower()


def test_timeout_returns_reportable_result_without_raising(tmp_path: Path) -> None:
    stub = _RecordingCommandRunner(
        error=subprocess.TimeoutExpired(cmd=["docker", "run"], timeout=1.0)
    )

    result = DockerRunner(command_runner=stub, timeout_seconds=1.0).run(
        _docker_manifest(), _TRIAL, workspace=tmp_path / "ws"
    )

    assert result.exit_code != 0
    assert "timed out" in result.stderr.lower()


def test_image_pull_failure_surfaces_as_nonzero_exit(tmp_path: Path) -> None:
    stub = _RecordingCommandRunner(
        result=subprocess.CompletedProcess(
            args=[], returncode=1, stdout="", stderr="Unable to find image 'bogus:latest' locally\n"
        )
    )

    result = DockerRunner(command_runner=stub).run(
        _docker_manifest(), _TRIAL, workspace=tmp_path / "ws"
    )

    assert result.exit_code == 1
    assert "unable to find image" in result.stderr.lower()


def test_missing_image_reference_returns_reportable_result_without_raising(tmp_path: Path) -> None:
    stub = _RecordingCommandRunner(
        result=subprocess.CompletedProcess(args=[], returncode=0, stdout="", stderr="")
    )
    # Non-docker manifests never reach DockerRunner via RunnerRegistry, but
    # `run` must still degrade gracefully rather than raise if it does.
    manifest = AgentManifest(
        id="command-agent",
        name="Command Agent",
        framework="raw-python",
        entrypoint=AgentEntrypoint(type=EntrypointType.COMMAND, command="echo hi"),
        runtime=AgentRuntime(type=RuntimeType.PROCESS),
        scenarios=["example-scenario"],
    )

    result = DockerRunner(command_runner=stub).run(manifest, _TRIAL, workspace=tmp_path / "ws")

    assert result.exit_code != 0
    assert "entrypoint.image" in result.stderr
    assert not stub.calls  # docker was never invoked
