"""Unit tests for `arena.reports.github_issues` (AAASM-4505): live GitHub
issue creation for routed Arena defeats, fingerprint-based duplicate
prevention, and token-presence gating.

**Every `gh` invocation here is mocked.** Like `test_runner_docker.py`
(`DockerRunner`), no test in this module shells out to a real `gh` binary,
makes a network call, or requires real GitHub credentials — every call is
routed through a `_RecordingCommandRunner` stub injected via the
`command_runner` parameter, which records the exact argv it was called with
and returns a canned `subprocess.CompletedProcess` instead of talking to
GitHub. This is the mechanism the ticket's safety instruction requires: no
`gh issue create`/`gh issue list` call anywhere in this file resolves to a
live invocation against `ai-agent-assembly/agent-assembly` or
`ai-agent-assembly/arena` — grep the argv assertions below and there is
nothing to run.
"""

from __future__ import annotations

import subprocess
from typing import Any

import pytest

from arena.reports.github_issues import (
    GH_TOKEN_ENV_VAR,
    GH_TOKEN_FALLBACK_ENV_VAR,
    GitHubIssueCreationError,
    create_issue_for_payload,
    create_issues_for_report,
    find_existing_issue,
)
from arena.reports.issue_payload import IssuePayload

_PAYLOAD = IssuePayload(
    title="[Arena Defeat] Critical escape: github-maintainer-dungeon/trial-1",
    body="**Category:** critical_escape\n**Scenario ID:** github-maintainer-dungeon\n",
    repo="ai-agent-assembly/agent-assembly",
    labels=("arena-defeat", "security", "critical-escape"),
    fingerprint="deadbeef" * 8,
)

_OTHER_PAYLOAD = IssuePayload(
    title="[Arena Defeat] Approval bypass: github-maintainer-dungeon/trial-2",
    body="**Category:** approval_bypass\n**Scenario ID:** github-maintainer-dungeon\n",
    repo="ai-agent-assembly/agent-assembly",
    labels=("arena-defeat", "security", "approval-bypass"),
    fingerprint="cafebabe" * 8,
)


class _RecordingCommandRunner:
    """Stub in place of `subprocess.run`: records the argv/kwargs it was
    called with and returns a queued canned result for each call in order.

    Mirrors `test_runner_docker.py`'s `_RecordingCommandRunner`.
    """

    def __init__(self, results: list[subprocess.CompletedProcess[str]]) -> None:
        self._results = list(results)
        self.calls: list[tuple[list[str], dict[str, Any]]] = []

    def __call__(self, argv: list[str], **kwargs: Any) -> subprocess.CompletedProcess[str]:
        self.calls.append((argv, kwargs))
        assert self._results, "command_runner called more times than results were queued"
        return self._results.pop(0)


def _completed(*, returncode: int = 0, stdout: str = "", stderr: str = "") -> Any:
    return subprocess.CompletedProcess(args=[], returncode=returncode, stdout=stdout, stderr=stderr)


@pytest.fixture(autouse=True)
def _ensure_token(monkeypatch: pytest.MonkeyPatch) -> None:
    """Most tests aren't exercising the token-gate itself — give them a token
    so they reach the (mocked) `gh` calls under test. Tests of the missing-
    token path explicitly `delenv` both vars themselves.
    """
    monkeypatch.setenv(GH_TOKEN_ENV_VAR, "test-token-not-real")
    monkeypatch.delenv(GH_TOKEN_FALLBACK_ENV_VAR, raising=False)


# --- find_existing_issue -----------------------------------------------


def test_find_existing_issue_returns_none_when_gh_reports_no_matches() -> None:
    stub = _RecordingCommandRunner([_completed(stdout="[]")])

    result = find_existing_issue(_PAYLOAD, command_runner=stub)

    assert result is None
    assert len(stub.calls) == 1
    argv, kwargs = stub.calls[0]
    assert argv[:3] == ["gh", "issue", "list"]
    assert "--repo" in argv and argv[argv.index("--repo") + 1] == _PAYLOAD.repo
    assert "--search" in argv
    assert _PAYLOAD.fingerprint in argv[argv.index("--search") + 1]
    assert "--state" in argv and argv[argv.index("--state") + 1] == "open"
    assert kwargs["capture_output"] is True
    assert kwargs["text"] is True


def test_find_existing_issue_returns_url_when_gh_reports_a_match() -> None:
    stub = _RecordingCommandRunner(
        [_completed(stdout='[{"number": 42, "url": "https://github.com/example/repo/issues/42"}]')]
    )

    result = find_existing_issue(_PAYLOAD, command_runner=stub)

    assert result == "https://github.com/example/repo/issues/42"


def test_find_existing_issue_raises_on_gh_failure() -> None:
    stub = _RecordingCommandRunner([_completed(returncode=1, stderr="gh: authentication failed")])

    with pytest.raises(GitHubIssueCreationError, match="authentication failed"):
        find_existing_issue(_PAYLOAD, command_runner=stub)


def test_find_existing_issue_raises_on_unparseable_json() -> None:
    stub = _RecordingCommandRunner([_completed(stdout="not json")])

    with pytest.raises(GitHubIssueCreationError, match="unparseable JSON"):
        find_existing_issue(_PAYLOAD, command_runner=stub)


# --- create_issue_for_payload -------------------------------------------


def test_create_issue_for_payload_creates_when_no_duplicate_exists() -> None:
    stub = _RecordingCommandRunner(
        [
            _completed(stdout="[]"),  # gh issue list: no existing match
            _completed(stdout="https://github.com/example/repo/issues/99\n"),  # gh issue create
        ]
    )

    result = create_issue_for_payload(_PAYLOAD, command_runner=stub)

    assert result.skipped_duplicate is False
    assert result.issue_url == "https://github.com/example/repo/issues/99"
    assert len(stub.calls) == 2

    create_argv, create_kwargs = stub.calls[1]
    assert create_argv[:3] == ["gh", "issue", "create"]
    assert create_argv[create_argv.index("--repo") + 1] == _PAYLOAD.repo
    assert create_argv[create_argv.index("--title") + 1] == _PAYLOAD.title
    body_arg = create_argv[create_argv.index("--body") + 1]
    assert _PAYLOAD.body in body_arg
    assert f"<!-- arena-fingerprint: {_PAYLOAD.fingerprint} -->" in body_arg
    for label in _PAYLOAD.labels:
        assert "--label" in create_argv
    label_positions = [i for i, a in enumerate(create_argv) if a == "--label"]
    assert {create_argv[i + 1] for i in label_positions} == set(_PAYLOAD.labels)
    assert create_kwargs["capture_output"] is True


def test_create_issue_for_payload_skips_creation_when_duplicate_exists() -> None:
    stub = _RecordingCommandRunner(
        [_completed(stdout='[{"number": 7, "url": "https://github.com/example/repo/issues/7"}]')]
    )

    result = create_issue_for_payload(_PAYLOAD, command_runner=stub)

    assert result.skipped_duplicate is True
    assert result.issue_url == "https://github.com/example/repo/issues/7"
    # Only the `gh issue list` lookup ran — `gh issue create` was never
    # invoked, proving duplicate detection actually prevents a second issue.
    assert len(stub.calls) == 1
    assert stub.calls[0][0][:3] == ["gh", "issue", "list"]


def test_create_issue_for_payload_raises_on_gh_create_failure() -> None:
    stub = _RecordingCommandRunner(
        [
            _completed(stdout="[]"),
            _completed(returncode=1, stderr="gh: repository not found"),
        ]
    )

    with pytest.raises(GitHubIssueCreationError, match="repository not found"):
        create_issue_for_payload(_PAYLOAD, command_runner=stub)


# --- create_issues_for_report -------------------------------------------


def test_create_issues_for_report_winning_match_makes_zero_calls(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # No token configured at all — proving the empty-payloads path neither
    # requires a token nor makes any command_runner call, exactly the
    # "winning match -> zero API calls attempted" contract.
    monkeypatch.delenv(GH_TOKEN_ENV_VAR, raising=False)
    monkeypatch.delenv(GH_TOKEN_FALLBACK_ENV_VAR, raising=False)
    stub = _RecordingCommandRunner([])

    results = create_issues_for_report([], command_runner=stub)

    assert results == []
    assert stub.calls == []


def test_create_issues_for_report_creates_one_issue_per_payload() -> None:
    stub = _RecordingCommandRunner(
        [
            _completed(stdout="[]"),
            _completed(stdout="https://github.com/example/repo/issues/1\n"),
            _completed(stdout="[]"),
            _completed(stdout="https://github.com/example/repo/issues/2\n"),
        ]
    )

    results = create_issues_for_report([_PAYLOAD, _OTHER_PAYLOAD], command_runner=stub)

    assert [r.issue_url for r in results] == [
        "https://github.com/example/repo/issues/1",
        "https://github.com/example/repo/issues/2",
    ]
    assert all(not r.skipped_duplicate for r in results)
    assert len(stub.calls) == 4


def test_create_issues_for_report_raises_clear_error_when_token_missing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv(GH_TOKEN_ENV_VAR, raising=False)
    monkeypatch.delenv(GH_TOKEN_FALLBACK_ENV_VAR, raising=False)
    stub = _RecordingCommandRunner([])

    with pytest.raises(GitHubIssueCreationError, match="GH_TOKEN"):
        create_issues_for_report([_PAYLOAD], command_runner=stub)

    # The token check must happen before any gh call is attempted.
    assert stub.calls == []


def test_create_issues_for_report_accepts_github_token_fallback(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv(GH_TOKEN_ENV_VAR, raising=False)
    monkeypatch.setenv(GH_TOKEN_FALLBACK_ENV_VAR, "test-token-not-real")
    stub = _RecordingCommandRunner(
        [_completed(stdout="[]"), _completed(stdout="https://github.com/example/repo/issues/3\n")]
    )

    results = create_issues_for_report([_PAYLOAD], command_runner=stub)

    assert results[0].issue_url == "https://github.com/example/repo/issues/3"
