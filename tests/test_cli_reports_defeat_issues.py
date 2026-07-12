"""Tests for the `aasm-arena reports defeat-issues` command (AAASM-4402)."""

from __future__ import annotations

from pathlib import Path

from typer.testing import CliRunner

from arena.cli import app

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


def test_defeat_issues_no_dry_run_is_not_implemented() -> None:
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
    assert "not implemented" in result.stdout
