"""Smoke tests for the aasm-arena CLI skeleton."""

from typer.testing import CliRunner

from arena.cli import app

runner = CliRunner()


def test_help_exits_zero() -> None:
    result = runner.invoke(app, ["--help"])
    assert result.exit_code == 0
    assert "aasm-arena" in result.stdout or "Usage" in result.stdout


def test_version_command_exits_zero() -> None:
    result = runner.invoke(app, ["version"])
    assert result.exit_code == 0
    assert "aasm-arena" in result.stdout
