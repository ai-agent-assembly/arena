"""Tests for the `aasm-arena reports defeat-issues` command (AAASM-4402's
`--dry-run` default, and AAASM-4505's `--no-dry-run` live issue creation).

The `--no-dry-run` tests below never invoke `gh` for real: `arena.cli`
imports `create_issues_for_report` by name from `arena.reports.github_issues`
(`from arena.reports.github_issues import ... create_issues_for_report`), so
`monkeypatch.setattr("arena.cli.create_issues_for_report", ...)` replaces
exactly the call site this command uses, with no real subprocess/`gh`
invocation anywhere in this file — `arena.reports.github_issues`'s own
`_RecordingCommandRunner`-based tests (`tests/test_reports_github_issues.py`)
cover the actual `gh` argv construction and duplicate-detection logic.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from typer.testing import CliRunner

from arena.cli import app
from arena.reports.github_issues import (
    GH_TOKEN_ENV_VAR,
    GH_TOKEN_FALLBACK_ENV_VAR,
    GitHubIssueCreationError,
    IssueCreationResult,
)
from arena.reports.issue_payload import IssuePayload

runner = CliRunner()

SAMPLES_ROOT = Path(__file__).parent.parent / "docs" / "samples"


def test_defeat_issues_winning_sample_reports_no_defeats() -> None:
    result = runner.invoke(
        app,
        ["reports", "defeat-issues", str(SAMPLES_ROOT / "winning-match" / "arena-report.json")],
    )

    assert result.exit_code == 0
    assert "No defeats found" in result.stdout


def test_defeat_issues_losing_sample_prints_payloads() -> None:
    result = runner.invoke(
        app,
        ["reports", "defeat-issues", str(SAMPLES_ROOT / "losing-match" / "arena-report.json")],
    )

    assert result.exit_code == 0
    assert "ai-agent-assembly/agent-assembly" in result.stdout
    assert "[Arena Defeat] Critical escape:" in result.stdout
    assert "fingerprint:" in result.stdout


def test_defeat_issues_no_dry_run_winning_sample_makes_zero_api_calls(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A winning report has no defeats, so `create_issues_for_report` (the
    only call site in this command that can reach the GitHub API) must never
    even be invoked — proven here by monkeypatching it to raise if called,
    with no token configured either, matching AC3's "zero API calls
    attempted at all" for a winning match.
    """
    monkeypatch.delenv(GH_TOKEN_ENV_VAR, raising=False)
    monkeypatch.delenv(GH_TOKEN_FALLBACK_ENV_VAR, raising=False)

    def _fail_if_called(payloads: list[IssuePayload]) -> list[IssueCreationResult]:
        raise AssertionError("create_issues_for_report must not be called for a winning report")

    monkeypatch.setattr("arena.cli.create_issues_for_report", _fail_if_called)

    result = runner.invoke(
        app,
        [
            "reports",
            "defeat-issues",
            str(SAMPLES_ROOT / "winning-match" / "arena-report.json"),
            "--no-dry-run",
        ],
    )

    assert result.exit_code == 0
    assert "No defeats found" in result.stdout


def test_defeat_issues_no_dry_run_missing_token_fails_clearly(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv(GH_TOKEN_ENV_VAR, raising=False)
    monkeypatch.delenv(GH_TOKEN_FALLBACK_ENV_VAR, raising=False)

    result = runner.invoke(
        app,
        [
            "reports",
            "defeat-issues",
            str(SAMPLES_ROOT / "losing-match" / "arena-report.json"),
            "--no-dry-run",
        ],
    )

    assert result.exit_code == 1
    assert "GH_TOKEN" in result.stdout
    assert "ARENA_DEFEAT_ISSUE_TOKEN" in result.stdout


def test_defeat_issues_no_dry_run_creates_and_reports_results(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv(GH_TOKEN_ENV_VAR, "test-token-not-real")

    calls: list[list[IssuePayload]] = []

    def _fake_create_issues_for_report(payloads: list[IssuePayload]) -> list[IssueCreationResult]:
        calls.append(payloads)
        results = []
        for index, payload in enumerate(payloads):
            if index == 0:
                results.append(
                    IssueCreationResult(
                        payload=payload,
                        skipped_duplicate=False,
                        issue_url=f"https://github.com/{payload.repo}/issues/101",
                    )
                )
            else:
                results.append(
                    IssueCreationResult(
                        payload=payload,
                        skipped_duplicate=True,
                        issue_url=f"https://github.com/{payload.repo}/issues/7",
                    )
                )
        return results

    monkeypatch.setattr("arena.cli.create_issues_for_report", _fake_create_issues_for_report)

    result = runner.invoke(
        app,
        [
            "reports",
            "defeat-issues",
            str(SAMPLES_ROOT / "losing-match" / "arena-report.json"),
            "--no-dry-run",
        ],
    )

    assert result.exit_code == 0
    assert len(calls) == 1
    assert len(calls[0]) > 1  # the losing sample has more than one defeat signal
    assert "created" in result.stdout
    assert "https://github.com/ai-agent-assembly/agent-assembly/issues/101" in result.stdout
    assert "skipped (duplicate" in result.stdout
    assert "https://github.com/ai-agent-assembly/agent-assembly/issues/7" in result.stdout


def test_defeat_issues_no_dry_run_surfaces_creation_error(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(GH_TOKEN_ENV_VAR, "test-token-not-real")

    def _fake_create_issues_for_report(payloads: list[IssuePayload]) -> list[IssueCreationResult]:
        raise GitHubIssueCreationError("`gh issue create` failed for 'example/repo': boom")

    monkeypatch.setattr("arena.cli.create_issues_for_report", _fake_create_issues_for_report)

    result = runner.invoke(
        app,
        [
            "reports",
            "defeat-issues",
            str(SAMPLES_ROOT / "losing-match" / "arena-report.json"),
            "--no-dry-run",
        ],
    )

    assert result.exit_code == 1
    assert "boom" in result.stdout
