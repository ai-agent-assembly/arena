"""Unit tests for the `NoOpRunner` placeholder execution backend."""

from __future__ import annotations

from pathlib import Path

from arena.models.manifest import (
    AgentEntrypoint,
    AgentManifest,
    AgentRuntime,
    EntrypointType,
    RuntimeType,
)
from arena.models.scenario import Decision, Severity, TrialSpec
from arena.runner.base import Runner
from arena.runner.noop import NoOpRunner

_MANIFEST = AgentManifest(
    id="noop-test-agent",
    name="No-op Test Agent",
    framework="raw-python",
    entrypoint=AgentEntrypoint(type=EntrypointType.COMMAND, command="echo hi"),
    runtime=AgentRuntime(type=RuntimeType.PROCESS),
    scenarios=["example-scenario"],
)

_TRIAL = TrialSpec(
    id="example-trial",
    description="A trial used only to exercise NoOpRunner.",
    expected={"some.action": Decision.ALLOW},
    severity=Severity.LOW,
)


def test_noop_runner_satisfies_runner_protocol() -> None:
    assert isinstance(NoOpRunner(), Runner)


def test_noop_runner_always_succeeds(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"

    result = NoOpRunner().run(_MANIFEST, _TRIAL, workspace=workspace)

    assert result.exit_code == 0
    assert result.stderr == ""
    assert "noop-test-agent" in result.stdout
    assert "example-trial" in result.stdout
    assert result.duration_seconds >= 0.0


def test_noop_runner_creates_workspace(tmp_path: Path) -> None:
    workspace = tmp_path / "nested" / "workspace"
    assert not workspace.exists()

    NoOpRunner().run(_MANIFEST, _TRIAL, workspace=workspace)

    assert workspace.is_dir()
