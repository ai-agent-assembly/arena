"""CLI tests for `aasm-arena agents list`."""

from __future__ import annotations

from pathlib import Path

from typer.testing import CliRunner

from arena.cli import app

runner = CliRunner()

FIXTURES_DIR = Path(__file__).parent / "fixtures" / "registry"
MIXED_OFFICIAL = FIXTURES_DIR / "mixed" / "official"
MIXED_COMMUNITY = FIXTURES_DIR / "mixed" / "community"
DUPLICATE_OFFICIAL = FIXTURES_DIR / "duplicate" / "official"
DUPLICATE_COMMUNITY = FIXTURES_DIR / "duplicate" / "community"


def _invoke(*args: str) -> object:
    return runner.invoke(
        app,
        [
            "agents",
            "list",
            "--official-root",
            str(MIXED_OFFICIAL),
            "--community-root",
            str(MIXED_COMMUNITY),
            *args,
        ],
    )


def test_list_empty_registry_exits_zero(tmp_path: Path) -> None:
    result = runner.invoke(
        app,
        [
            "agents",
            "list",
            "--official-root",
            str(tmp_path / "official"),
            "--community-root",
            str(tmp_path / "community"),
        ],
    )

    assert result.exit_code == 0
    assert "No agents found" in result.stdout


def test_list_mixed_registry_shows_all_agents() -> None:
    result = _invoke()

    assert result.exit_code == 0
    assert "agent-alpha" in result.stdout
    assert "agent-beta" in result.stdout
    assert "agent-gamma" in result.stdout


def test_list_filters_by_framework() -> None:
    result = _invoke("--framework", "raw-python")

    assert result.exit_code == 0
    assert "agent-alpha" in result.stdout
    assert "agent-gamma" in result.stdout
    assert "agent-beta" not in result.stdout


def test_list_filters_by_scenario() -> None:
    result = _invoke("--scenario", "scenario-b")

    assert result.exit_code == 0
    assert "agent-beta" in result.stdout
    assert "agent-gamma" in result.stdout
    assert "agent-alpha" not in result.stdout


def test_list_filters_by_source() -> None:
    result = _invoke("--source", "official")

    assert result.exit_code == 0
    assert "agent-alpha" in result.stdout
    assert "agent-beta" not in result.stdout
    assert "agent-gamma" not in result.stdout


def test_list_duplicate_id_exits_nonzero() -> None:
    result = runner.invoke(
        app,
        [
            "agents",
            "list",
            "--official-root",
            str(DUPLICATE_OFFICIAL),
            "--community-root",
            str(DUPLICATE_COMMUNITY),
        ],
    )

    assert result.exit_code != 0
    assert "duplicate agent id" in " ".join(result.stdout.split())
