"""Tests for the `aasm-arena scenarios validate` command."""

from __future__ import annotations

from pathlib import Path

from typer.testing import CliRunner

from arena.cli import app

runner = CliRunner()

FIXTURES_DIR = Path(__file__).parent / "fixtures" / "scenarios"
MISSING_TRIAL_ROOT = Path(__file__).parent / "fixtures" / "missing_trial_scenario_root"


def test_validate_single_scenario_folder_exits_zero() -> None:
    result = runner.invoke(app, ["scenarios", "validate", str(FIXTURES_DIR / "example-scenario")])

    assert result.exit_code == 0
    assert "example-scenario" in result.stdout


def test_validate_registry_root_exits_zero() -> None:
    result = runner.invoke(app, ["scenarios", "validate", str(FIXTURES_DIR)])

    assert result.exit_code == 0
    assert "example-scenario" in result.stdout


def test_validate_missing_trial_reference_exits_nonzero() -> None:
    result = runner.invoke(
        app,
        ["scenarios", "validate", str(MISSING_TRIAL_ROOT / "missing-trial-scenario")],
    )

    assert result.exit_code == 1
    assert "FAILED" in result.stdout
