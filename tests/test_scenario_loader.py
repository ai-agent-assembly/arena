"""Unit tests for the scenario/trial YAML loader."""

from __future__ import annotations

from pathlib import Path

import pytest

from arena.models.manifest import (
    AgentEntrypoint,
    AgentFramework,
    AgentManifest,
    AgentRuntime,
    BehaviorProfile,
    EntrypointType,
    RuntimeType,
)
from arena.scenarios.loader import (
    ScenarioLoadError,
    load_scenario,
    load_scenario_registry,
    load_trial,
    validate_trial_behaviors,
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


# --- validate_trial_behaviors (AAASM-4404) ------------------------------


def _manifest(agent_id: str, behaviors: list[BehaviorProfile] | None = None) -> AgentManifest:
    return AgentManifest(
        id=agent_id,
        name=agent_id.title(),
        framework=AgentFramework.RAW_PYTHON,
        entrypoint=AgentEntrypoint(type=EntrypointType.COMMAND, command="python main.py"),
        runtime=AgentRuntime(type=RuntimeType.PROCESS),
        scenarios=["example-scenario"],
        behaviors=behaviors or [],
    )


def test_validate_trial_behaviors_passes_when_behavior_id_is_none() -> None:
    # Backward compatibility: a bundle whose trials don't set behavior_id at
    # all (every trial written before AAASM-4404) must validate cleanly
    # against any compatible agents, including agents with no behaviors.
    bundle = load_scenario(FIXTURES_DIR / "example-scenario")

    validate_trial_behaviors(bundle, [_manifest("agent-one")])


def test_validate_trial_behaviors_passes_when_declared_by_compatible_agent(
    tmp_path: Path,
) -> None:
    scenario_dir = tmp_path / "behavior-scenario"
    trials_dir = scenario_dir / "trials"
    trials_dir.mkdir(parents=True)
    (scenario_dir / "scenario.yaml").write_text(
        "id: behavior-scenario\n"
        "name: Behavior Scenario\n"
        "description: Scenario used for behavior_id cross-referential tests.\n"
        "trials:\n"
        "  - behavior-trial\n"
    )
    (trials_dir / "behavior-trial.yaml").write_text(
        "id: behavior-trial\n"
        "description: A trial that targets a specific behavior profile.\n"
        "expected:\n"
        "  some.action: deny\n"
        "severity: high\n"
        "behavior_id: secret-seeking\n"
    )
    bundle = load_scenario(scenario_dir)

    agent = _manifest(
        "agent-with-behavior",
        behaviors=[BehaviorProfile(id="secret-seeking", description="Reads a secrets file.")],
    )

    validate_trial_behaviors(bundle, [agent])


def test_validate_trial_behaviors_raises_when_unsupported_by_any_compatible_agent(
    tmp_path: Path,
) -> None:
    scenario_dir = tmp_path / "behavior-scenario"
    trials_dir = scenario_dir / "trials"
    trials_dir.mkdir(parents=True)
    (scenario_dir / "scenario.yaml").write_text(
        "id: behavior-scenario\n"
        "name: Behavior Scenario\n"
        "description: Scenario used for behavior_id cross-referential tests.\n"
        "trials:\n"
        "  - behavior-trial\n"
    )
    (trials_dir / "behavior-trial.yaml").write_text(
        "id: behavior-trial\n"
        "description: A trial that targets a specific behavior profile.\n"
        "expected:\n"
        "  some.action: deny\n"
        "severity: high\n"
        "behavior_id: secret-seeking\n"
    )
    bundle = load_scenario(scenario_dir)

    # This agent is compatible with the scenario but declares no
    # "secret-seeking" behavior (in fact, no behaviors at all) — the trial's
    # behavior_id reference can never be satisfied.
    agent = _manifest("agent-without-behavior")

    with pytest.raises(ScenarioLoadError, match="secret-seeking") as exc_info:
        validate_trial_behaviors(bundle, [agent])

    message = str(exc_info.value)
    assert "behavior-trial" in message
    assert "behavior-scenario" in message
    assert "agent-without-behavior" in message
