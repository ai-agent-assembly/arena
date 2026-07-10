"""Unit tests for the scenario/trial YAML loader."""

from __future__ import annotations

from pathlib import Path

import pytest

from arena.scenarios.loader import (
    ScenarioLoadError,
    load_scenario,
    load_scenario_registry,
    load_trial,
)

FIXTURES_DIR = Path(__file__).parent / "fixtures" / "scenarios"
MISSING_TRIAL_ROOT = Path(__file__).parent / "fixtures" / "missing_trial_scenario_root"


def test_load_scenario_valid_fixture_resolves_trials() -> None:
    bundle = load_scenario(FIXTURES_DIR / "example-scenario")

    assert bundle.scenario.id == "example-scenario"
    assert [trial.id for trial in bundle.trials] == [
        "happy-path-example",
        "denied-write-example",
    ]


def test_load_trial_valid_fixture() -> None:
    trial = load_trial(FIXTURES_DIR / "example-scenario" / "trials" / "happy-path-example.yaml")

    assert trial.id == "happy-path-example"
    assert trial.severity.value == "low"


def test_load_scenario_missing_directory_raises() -> None:
    with pytest.raises(ScenarioLoadError, match="no such directory"):
        load_scenario(FIXTURES_DIR / "does-not-exist")


def test_load_scenario_missing_trial_reference_raises() -> None:
    with pytest.raises(ScenarioLoadError, match="does-not-exist"):
        load_scenario(MISSING_TRIAL_ROOT / "missing-trial-scenario")


def test_load_trial_missing_file_raises() -> None:
    with pytest.raises(ScenarioLoadError, match="no such file"):
        load_trial(FIXTURES_DIR / "example-scenario" / "trials" / "nope.yaml")


def test_load_scenario_malformed_yaml_raises(tmp_path: Path) -> None:
    scenario_dir = tmp_path / "broken-scenario"
    scenario_dir.mkdir()
    (scenario_dir / "scenario.yaml").write_text("id: [this is not valid: yaml")

    with pytest.raises(ScenarioLoadError, match="invalid YAML"):
        load_scenario(scenario_dir)


def test_load_scenario_invalid_expected_decision_raises(tmp_path: Path) -> None:
    scenario_dir = tmp_path / "bad-decision-scenario"
    trials_dir = scenario_dir / "trials"
    trials_dir.mkdir(parents=True)
    (scenario_dir / "scenario.yaml").write_text(
        "id: bad-decision-scenario\n"
        "name: Bad Decision Scenario\n"
        "description: Has a trial with an invalid expected decision.\n"
        "trials:\n"
        "  - bad-decision-trial\n"
    )
    (trials_dir / "bad-decision-trial.yaml").write_text(
        "id: bad-decision-trial\n"
        "description: Uses an expected decision outside the vocabulary.\n"
        "expected:\n"
        "  some.action: permit\n"
        "severity: high\n"
    )

    with pytest.raises(ScenarioLoadError, match="invalid trial spec"):
        load_scenario(scenario_dir)


def test_load_scenario_malformed_victory_conditions_raises(tmp_path: Path) -> None:
    scenario_dir = tmp_path / "bad-victory-scenario"
    trials_dir = scenario_dir / "trials"
    trials_dir.mkdir(parents=True)
    (scenario_dir / "scenario.yaml").write_text(
        "id: bad-victory-scenario\n"
        "name: Bad Victory Scenario\n"
        "description: Has malformed victory_conditions.\n"
        "victory_conditions:\n"
        "  critical_escapes: -1\n"
        "trials:\n"
        "  - some-trial\n"
    )
    (trials_dir / "some-trial.yaml").write_text(
        "id: some-trial\ndescription: A trial.\nexpected:\n  some.action: allow\nseverity: low\n"
    )

    with pytest.raises(ScenarioLoadError, match="invalid scenario spec"):
        load_scenario(scenario_dir)


def test_load_scenario_registry_loads_all_scenario_folders() -> None:
    registry = load_scenario_registry(FIXTURES_DIR)

    assert set(registry) >= {"example-scenario"}
    assert registry["example-scenario"].scenario.name == "Example Scenario"


def test_load_scenario_registry_missing_root_raises() -> None:
    with pytest.raises(ScenarioLoadError, match="no such directory"):
        load_scenario_registry(FIXTURES_DIR / "does-not-exist")


def test_load_scenario_registry_ignores_non_scenario_subdirectories(
    tmp_path: Path,
) -> None:
    (tmp_path / "not-a-scenario").mkdir()
    (tmp_path / "not-a-scenario" / "README.md").write_text("not a scenario dir")

    registry = load_scenario_registry(tmp_path)

    assert registry == {}
