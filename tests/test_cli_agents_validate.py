"""CLI tests for `aasm-arena agents validate`."""

from __future__ import annotations

from pathlib import Path

from typer.testing import CliRunner

from arena.cli import app

runner = CliRunner()

EXAMPLES_DIR = Path(__file__).parent.parent / "examples" / "manifests"
VALID_MANIFEST_PATH = EXAMPLES_DIR / "raw-python-issue-triager.yaml"
INVALID_MANIFEST_PATH = Path(__file__).parent / "fixtures" / "manifests" / "invalid.yaml"

COMMUNITY_FIXTURES_DIR = Path(__file__).parent / "fixtures" / "community_agents"
VALID_ONLY_DIR = COMMUNITY_FIXTURES_DIR / "valid_only"
WITH_INVALID_SCHEMA_DIR = COMMUNITY_FIXTURES_DIR / "with_invalid_schema"
WITH_ID_MISMATCH_DIR = COMMUNITY_FIXTURES_DIR / "with_id_mismatch"
WITH_MISSING_MANIFEST_DIR = COMMUNITY_FIXTURES_DIR / "with_missing_manifest"
EMPTY_DIR = COMMUNITY_FIXTURES_DIR / "empty"


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


def test_validate_directory_all_valid_exits_zero() -> None:
    """`agents validate <dir>` (used in CI for `agents/community`) validates
    every `<agent-id>/agent.yaml` under the directory.
    """
    result = runner.invoke(app, ["agents", "validate", str(VALID_ONLY_DIR)])
    output = " ".join(result.stdout.split())

    assert result.exit_code == 0
    assert "agent-x is a valid manifest" in output


def test_validate_directory_with_invalid_schema_exits_nonzero() -> None:
    """A manifest that fails schema validation fails CI with an actionable,
    field-level message — this is what community submissions with a bad
    `agent.yaml` see in the GitHub Actions log (AAASM-4395 AC3).
    """
    result = runner.invoke(app, ["agents", "validate", str(WITH_INVALID_SCHEMA_DIR)])
    output = " ".join(result.stdout.split())

    assert result.exit_code != 0
    assert "test-invalid" in output
    assert "invalid" in output
    # Error output should identify the offending fields.
    assert "id" in output
    assert "runtime" in output
    # The other, valid submission in the same directory is still reported.
    assert "agent-x is a valid manifest" in output


def test_validate_directory_with_id_mismatch_exits_nonzero() -> None:
    result = runner.invoke(app, ["agents", "validate", str(WITH_ID_MISMATCH_DIR)])
    output = " ".join(result.stdout.split())

    assert result.exit_code != 0
    assert "wrong-dir-name" in output
    assert "actual-agent-id" in output
    assert "does not match directory name" in output


def test_validate_directory_with_missing_manifest_exits_nonzero() -> None:
    result = runner.invoke(app, ["agents", "validate", str(WITH_MISSING_MANIFEST_DIR)])
    output = " ".join(result.stdout.split())

    assert result.exit_code != 0
    assert "no-manifest-agent" in output
    assert "missing required" in output


def test_validate_empty_directory_exits_zero() -> None:
    """No submissions under the directory is a valid, no-op state — the
    community validation workflow must not fail when no PR touches
    `agents/community/**`.
    """
    result = runner.invoke(app, ["agents", "validate", str(EMPTY_DIR)])
    output = " ".join(result.stdout.split())

    assert result.exit_code == 0
    assert "No agent submissions found" in output
