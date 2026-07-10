"""Unit tests for `emit_action_attempt` (AAASM-4379): the emit-side helper
agent scripts call to report an attempted action as a stdout marker line.
"""

from __future__ import annotations

import io
import json

import pytest

from arena.integrations.emit import ACTION_ATTEMPT_MARKER_PREFIX, emit_action_attempt
from arena.integrations.models import ArenaActionAttempt


def test_emit_prints_prefixed_json_marker_and_returns_attempt() -> None:
    stream = io.StringIO()

    attempt = emit_action_attempt(
        tool="github.contents.write",
        resource="src/app.py",
        framework="raw-python",
        scenario_id="github-maintainer-dungeon",
        args={"branch": "main"},
        context="test attempt",
        agent_id="test-agent",
        trial_id="prompt-injection-code-write",
        stream=stream,
    )

    output = stream.getvalue()
    assert output.startswith(ACTION_ATTEMPT_MARKER_PREFIX)
    assert output.endswith("\n")

    payload = json.loads(output[len(ACTION_ATTEMPT_MARKER_PREFIX) :])
    assert payload["agent_id"] == "test-agent"
    assert payload["tool"] == "github.contents.write"
    assert payload["resource"] == "src/app.py"
    assert payload["args"] == {"branch": "main"}

    assert isinstance(attempt, ArenaActionAttempt)
    assert attempt.agent_id == "test-agent"
    assert attempt.trial_id == "prompt-injection-code-write"


def test_emit_defaults_agent_id_and_trial_id_from_environment(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("ARENA_AGENT_ID", "env-agent")
    monkeypatch.setenv("ARENA_TRIAL_ID", "env-trial")
    stream = io.StringIO()

    attempt = emit_action_attempt(
        tool="secrets.read",
        resource="secrets/fake_api_keys.env",
        framework="raw-python",
        scenario_id="github-maintainer-dungeon",
        stream=stream,
    )

    assert attempt.agent_id == "env-agent"
    assert attempt.trial_id == "env-trial"


def test_emit_explicit_agent_id_and_trial_id_override_environment(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("ARENA_AGENT_ID", "env-agent")
    monkeypatch.setenv("ARENA_TRIAL_ID", "env-trial")
    stream = io.StringIO()

    attempt = emit_action_attempt(
        tool="secrets.read",
        resource="secrets/fake_api_keys.env",
        framework="raw-python",
        scenario_id="github-maintainer-dungeon",
        agent_id="explicit-agent",
        trial_id="explicit-trial",
        stream=stream,
    )

    assert attempt.agent_id == "explicit-agent"
    assert attempt.trial_id == "explicit-trial"


def test_emit_raises_without_agent_id(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("ARENA_AGENT_ID", raising=False)
    monkeypatch.setenv("ARENA_TRIAL_ID", "env-trial")

    with pytest.raises(ValueError, match="agent_id"):
        emit_action_attempt(
            tool="secrets.read",
            resource="secrets/fake_api_keys.env",
            framework="raw-python",
            scenario_id="github-maintainer-dungeon",
            stream=io.StringIO(),
        )


def test_emit_raises_without_trial_id(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("ARENA_AGENT_ID", "env-agent")
    monkeypatch.delenv("ARENA_TRIAL_ID", raising=False)

    with pytest.raises(ValueError, match="trial_id"):
        emit_action_attempt(
            tool="secrets.read",
            resource="secrets/fake_api_keys.env",
            framework="raw-python",
            scenario_id="github-maintainer-dungeon",
            stream=io.StringIO(),
        )


def test_emit_defaults_args_to_empty_dict_and_context_to_none() -> None:
    stream = io.StringIO()

    attempt = emit_action_attempt(
        tool="shell.exec",
        resource="workspace",
        framework="raw-python",
        scenario_id="github-maintainer-dungeon",
        agent_id="test-agent",
        trial_id="destructive-command-drop",
        stream=stream,
    )

    assert attempt.args == {}
    assert attempt.context is None
