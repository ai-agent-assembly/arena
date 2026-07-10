"""YAML loader/validator for scenario and trial specs.

Layout convention for a single scenario folder:

    <scenario-dir>/
        scenario.yaml       # a ScenarioSpec (id, name, description, ...)
        trials/
            <trial-id>.yaml # a TrialSpec, one per file
            ...

`load_scenario` reads that layout and resolves the id references in
`ScenarioSpec.trials` against the `TrialSpec`s found under `trials/`,
raising `ScenarioLoadError` if a referenced trial is missing or a YAML file
fails schema validation. `load_scenario_registry` walks a directory of such
scenario folders (e.g. a top-level `scenarios/` directory) and loads all of
them.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml
from pydantic import ValidationError

from arena.models.manifest import AgentManifest
from arena.models.scenario import ScenarioSpec, TrialSpec

_SCENARIO_FILENAME = "scenario.yaml"
_TRIALS_DIRNAME = "trials"


class ScenarioLoadError(Exception):
    """Raised when a scenario/trial YAML file is missing, malformed, or invalid."""


@dataclass(frozen=True)
class ScenarioBundle:
    """A `ScenarioSpec` together with its fully resolved `TrialSpec`s."""

    scenario: ScenarioSpec
    trials: list[TrialSpec]


def _read_yaml_mapping(path: Path) -> dict[str, Any]:
    if not path.is_file():
        raise ScenarioLoadError(f"{path}: no such file")
    try:
        raw = yaml.safe_load(path.read_text())
    except yaml.YAMLError as exc:
        raise ScenarioLoadError(f"{path}: invalid YAML — {exc}") from exc
    if not isinstance(raw, dict):
        raise ScenarioLoadError(f"{path}: expected a YAML mapping at the top level")
    return raw


def load_trial(path: Path) -> TrialSpec:
    """Load and validate a single trial YAML file into a `TrialSpec`."""
    raw = _read_yaml_mapping(path)
    try:
        return TrialSpec.model_validate(raw)
    except ValidationError as exc:
        raise ScenarioLoadError(f"{path}: invalid trial spec — {exc}") from exc


def load_scenario(scenario_dir: Path) -> ScenarioBundle:
    """Load a scenario folder into a `ScenarioBundle`.

    Reads `<scenario_dir>/scenario.yaml` and every `*.yaml`/`*.yml` file
    under `<scenario_dir>/trials/`, then validates that every trial id the
    scenario references actually resolved to a loaded `TrialSpec`.
    """
    if not scenario_dir.is_dir():
        raise ScenarioLoadError(f"{scenario_dir}: no such directory")

    scenario_path = scenario_dir / _SCENARIO_FILENAME
    raw_scenario = _read_yaml_mapping(scenario_path)
    try:
        scenario = ScenarioSpec.model_validate(raw_scenario)
    except ValidationError as exc:
        raise ScenarioLoadError(f"{scenario_path}: invalid scenario spec — {exc}") from exc

    trials_dir = scenario_dir / _TRIALS_DIRNAME
    trial_files = (
        sorted(p for p in trials_dir.glob("*") if p.suffix in (".yaml", ".yml"))
        if trials_dir.is_dir()
        else []
    )

    trials_by_id: dict[str, TrialSpec] = {}
    for trial_path in trial_files:
        trial = load_trial(trial_path)
        if trial.id in trials_by_id:
            raise ScenarioLoadError(
                f"{scenario_dir}: duplicate trial id {trial.id!r} "
                f"(also defined in {trials_dir / (trial.id + trial_path.suffix)})"
            )
        trials_by_id[trial.id] = trial

    missing = [trial_id for trial_id in scenario.trials if trial_id not in trials_by_id]
    if missing:
        raise ScenarioLoadError(
            f"{scenario_dir}: scenario {scenario.id!r} references trial(s) "
            f"{missing!r} not found under {trials_dir}"
        )

    resolved_trials = [trials_by_id[trial_id] for trial_id in scenario.trials]
    return ScenarioBundle(scenario=scenario, trials=resolved_trials)


def validate_trial_behaviors(
    bundle: ScenarioBundle, compatible_agents: Sequence[AgentManifest]
) -> None:
    """Validate every trial's `behavior_id` (AAASM-4404), if set, against
    the behaviors declared by agents compatible with this scenario.

    `compatible_agents` is the set of `AgentManifest`s eligible to run
    `bundle.scenario` — i.e. the manifests for which `bundle.scenario.id` is
    a member of `AgentManifest.scenarios`, exactly what
    `AgentRegistry.filter(scenario=...)` (`arena.registry.discovery`)
    already computes. This function doesn't discover that set itself so it
    stays decoupled from agent registry discovery; callers (e.g.
    `arena.runner.match.run_match`) pass it in.

    A trial with `behavior_id=None` is unaffected — behavior profiles are
    opt-in per trial. A trial whose `behavior_id` is set but not declared by
    *any* compatible agent's `behaviors` list fails validation: nothing
    could ever satisfy that trial's expectation, which the schema should
    catch here rather than surfacing as a mysterious runtime skip later.

    Raises:
        ScenarioLoadError: a trial references a `behavior_id` no compatible
            agent declares.
    """
    declared_behavior_ids = {
        behavior.id for agent in compatible_agents for behavior in agent.behaviors
    }
    for trial in bundle.trials:
        if trial.behavior_id is None:
            continue
        if trial.behavior_id not in declared_behavior_ids:
            compatible_agent_ids = sorted(agent.id for agent in compatible_agents)
            raise ScenarioLoadError(
                f"scenario {bundle.scenario.id!r} trial {trial.id!r} references "
                f"behavior_id {trial.behavior_id!r}, which is not declared by any "
                f"agent compatible with this scenario "
                f"(compatible agents: {compatible_agent_ids!r})"
            )


def load_scenario_registry(root: Path) -> dict[str, ScenarioBundle]:
    """Load every scenario folder directly under `root`.

    A "scenario folder" is any subdirectory of `root` containing a
    `scenario.yaml` file; other subdirectories are ignored. Raises
    `ScenarioLoadError` if any scenario fails to load or two scenario
    folders declare the same scenario id.
    """
    if not root.is_dir():
        raise ScenarioLoadError(f"{root}: no such directory")

    registry: dict[str, ScenarioBundle] = {}
    for entry in sorted(root.iterdir()):
        if not entry.is_dir() or not (entry / _SCENARIO_FILENAME).is_file():
            continue
        bundle = load_scenario(entry)
        if bundle.scenario.id in registry:
            raise ScenarioLoadError(
                f"{root}: duplicate scenario id {bundle.scenario.id!r} "
                f"(also defined elsewhere in {root})"
            )
        registry[bundle.scenario.id] = bundle

    return registry
