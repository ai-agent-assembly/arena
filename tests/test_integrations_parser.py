"""Unit tests for `parse_action_attempts` (AAASM-4379): recovering
`ArenaActionAttempt`s from raw captured agent stdout, including malformed
marker handling.
"""

from __future__ import annotations

import io

from arena.integrations.emit import emit_action_attempt
from arena.integrations.parser import parse_action_attempts


def _marker_line(**kwargs: object) -> str:
    stream = io.StringIO()
    emit_action_attempt(stream=stream, **kwargs)  # type: ignore[arg-type]
    return stream.getvalue()


def test_parse_zero_markers_from_plain_stdout() -> None:
    stdout = "just some ordinary agent log output\nnothing to see here\n"

    result = parse_action_attempts(stdout)

    assert result.attempts == ()
    assert result.errors == ()


def test_parse_single_marker() -> None:
    marker = _marker_line(
        tool="github.issues.comment",
        resource="issues/bug_report_login_timeout.json",
        framework="raw-python",
        scenario_id="github-maintainer-dungeon",
        agent_id="raw-python-issue-triager",
        trial_id="issue-triage-happy-path",
    )
    stdout = f"[raw-python-issue-triager] handling trial\n{marker}[raw-python-issue-triager] done\n"

    result = parse_action_attempts(stdout)

    assert len(result.attempts) == 1
    assert result.errors == ()
    attempt = result.attempts[0]
    assert attempt.tool == "github.issues.comment"
    assert attempt.trial_id == "issue-triage-happy-path"


def test_parse_multiple_markers_interspersed_with_log_lines() -> None:
    marker_one = _marker_line(
        tool="github.issues.comment",
        resource="issue#1",
        framework="raw-python",
        scenario_id="github-maintainer-dungeon",
        agent_id="agent-a",
        trial_id="trial-a",
    )
    marker_two = _marker_line(
        tool="secrets.read",
        resource="secrets/fake_api_keys.env",
        framework="raw-python",
        scenario_id="github-maintainer-dungeon",
        agent_id="agent-a",
        trial_id="trial-b",
    )
    stdout = f"starting up\n{marker_one}some log line\n{marker_two}shutting down\n"

    result = parse_action_attempts(stdout)

    assert len(result.attempts) == 2
    assert result.errors == ()
    assert [a.trial_id for a in result.attempts] == ["trial-a", "trial-b"]


def test_parse_skips_malformed_json_marker_and_records_error() -> None:
    stdout = "ARENA_ACTION_ATTEMPT: {not valid json\n"

    result = parse_action_attempts(stdout)

    assert result.attempts == ()
    assert len(result.errors) == 1
    assert "line 1" in result.errors[0]
    assert "invalid JSON" in result.errors[0]


def test_parse_skips_marker_failing_schema_validation_and_records_error() -> None:
    # Valid JSON, but missing every required ArenaActionAttempt field.
    stdout = 'ARENA_ACTION_ATTEMPT: {"some_other_field": "value"}\n'

    result = parse_action_attempts(stdout)

    assert result.attempts == ()
    assert len(result.errors) == 1
    assert "line 1" in result.errors[0]
    assert "invalid ArenaActionAttempt payload" in result.errors[0]


def test_parse_one_malformed_marker_does_not_prevent_recovering_valid_ones() -> None:
    good_marker = _marker_line(
        tool="shell.exec",
        resource="workspace",
        framework="raw-python",
        scenario_id="github-maintainer-dungeon",
        agent_id="agent-a",
        trial_id="destructive-command-drop",
    )
    stdout = f"ARENA_ACTION_ATTEMPT: {{broken\n{good_marker}"

    result = parse_action_attempts(stdout)

    assert len(result.attempts) == 1
    assert result.attempts[0].trial_id == "destructive-command-drop"
    assert len(result.errors) == 1
