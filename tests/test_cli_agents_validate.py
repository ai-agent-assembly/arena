"""CLI tests for `aasm-arena agents validate`."""

from __future__ import annotations

from pathlib import Path

from typer.testing import CliRunner

from arena.cli import app

runner = CliRunner()

EXAMPLES_DIR = Path(__file__).parent.parent / "examples" / "manifests"
VALID_MANIFEST_PATH = EXAMPLES_DIR / "raw-python-issue-triager.yaml"
INVALID_MANIFEST_PATH = Path(__file__).parent / "fixtures" / "manifests" / "invalid.yaml"


def test_validate_valid_manifest_exits_zero() -> None:
    result = runner.invoke(app, ["agents", "validate", str(VALID_MANIFEST_PATH)])
    output = " ".join(result.stdout.split())

    assert result.exit_code == 0
    assert "valid manifest" in output
    assert "raw-python-issue-triager" in output


def test_validate_invalid_manifest_exits_nonzero() -> None:
    result = runner.invoke(app, ["agents", "validate", str(INVALID_MANIFEST_PATH)])
    output = " ".join(result.stdout.split())

    assert result.exit_code != 0
    assert "invalid" in output
    # Error output should identify the offending fields.
    assert "id" in output
    assert "runtime" in output


def test_validate_missing_file_exits_nonzero() -> None:
    result = runner.invoke(app, ["agents", "validate", "/no/such/agent.yaml"])

    assert result.exit_code != 0
