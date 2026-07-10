"""Match orchestration: load a scenario, select agents, run every trial for
every selected agent through a `Runner`, and emit lifecycle events in order.

This module owns the *orchestration* seam described in AAASM-4372's proposed
design (`scenario + agents -> match id -> run trials -> launch agent ->
collect action attempts -> ...`) up to and including "launch agent" via the
`Runner` protocol (`arena.runner.base`). Real agent execution now exists —
`ProcessRunner` (AAASM-4374) for `COMMAND` entrypoints and `DockerRunner`
(AAASM-4375) for `DOCKER` entrypoints, both registered in
`default_runner_registry()`. This module intentionally does not implement:

* Calling agent-assembly to collect real governance decisions and comparing
  them against `TrialSpec.expected` — AAASM-4377.

Because that doesn't exist yet, `TrialOutcome.passed` here is a placeholder
proxy (`AgentRunResult.exit_code == 0`), not a real decision comparison, and
`MatchResult.critical_escapes` only counts non-zero exits on
`CRITICAL`-severity trials. That's the best signal available until
AAASM-4377 lands — callers must not treat it as a real governance verdict.
"""

from __future__ import annotations

import uuid
from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path

from arena.models.manifest import AgentManifest, EntrypointType
from arena.models.scenario import ScenarioSpec, TrialSpec
from arena.registry.discovery import (
    AgentRegistry,
    RegisteredAgent,
    RegistryLoadError,
    discover_agents,
)
from arena.runner.base import AgentRunResult, Runner
from arena.runner.docker import DockerRunner
from arena.runner.events import MatchEvent, MatchEventType
from arena.runner.process import ProcessRunner
from arena.scenarios.loader import ScenarioLoadError, load_scenario_registry


class MatchOrchestrationError(Exception):
    """Raised when a match cannot be set up or run: unknown scenario id, no
    compatible agents, a bad `--agent` filter, or an unregistered entrypoint
    type in the `RunnerRegistry`.
    """


@dataclass(frozen=True)
class RunnerRegistry:
    """Maps an agent's `EntrypointType` to the `Runner` that executes it.

    This is the extension point AAASM-4374/4375 plug into: each registers
    its concrete `Runner` for the entrypoint type it handles, instead of
    orchestration needing to know about `ProcessRunner`/`DockerRunner` by
    name.
    """

    runners: Mapping[EntrypointType, Runner]

    def resolve(self, manifest: AgentManifest) -> Runner:
        runner = self.runners.get(manifest.entrypoint.type)
        if runner is None:
            raise MatchOrchestrationError(
                f"no Runner registered for entrypoint type "
                f"{manifest.entrypoint.type.value!r} (agent {manifest.id!r})"
            )
        return runner


def default_runner_registry() -> RunnerRegistry:
    """The out-of-the-box registry: real execution for both `COMMAND`
    (`ProcessRunner`, AAASM-4374) and `DOCKER` (`DockerRunner`, AAASM-4375)
    entrypoints. `NoOpRunner` is no longer used here — it remains available
    for tests/callers that want a runner with no side effects.
    """
    return RunnerRegistry(
        {
            EntrypointType.COMMAND: ProcessRunner(),
            EntrypointType.DOCKER: DockerRunner(),
        }
    )


@dataclass(frozen=True)
class MatchConfig:
    """Where to load scenarios/agents from, and where to write match output."""

    scenarios_root: Path = Path("scenarios")
    official_root: Path = Path("agents/official")
    community_root: Path = Path("agents/community")
    #: Root directory each match's report workspace (`<output_root>/<match-id>/`)
    #: is created under. Kept separate from the `arena.reports` Python
    #: package (which will hold report-*rendering* logic) — this is on-disk
    #: generated output, not source.
    output_root: Path = Path("runs")
    runner_registry: RunnerRegistry = field(default_factory=default_runner_registry)


@dataclass(frozen=True)
class TrialOutcome:
    """One (agent, trial) run's placeholder pass/fail.

    `passed` is a proxy (`result.exit_code == 0`) until AAASM-4377 wires in
    real agent-assembly decisions and can compare them against
    `trial.expected`. `error` is set when the `Runner` raised instead of
    returning an `AgentRunResult`; `result` is still populated in that case
    with a synthesized failure result so callers don't need to branch.
    """

    trial: TrialSpec
    agent_id: str
    result: AgentRunResult
    passed: bool
    error: str | None = None


@dataclass(frozen=True)
class MatchResult:
    """The full outcome of one `run_match` call."""

    match_id: str
    scenario: ScenarioSpec
    workspace: Path
    events: tuple[MatchEvent, ...]
    trial_outcomes: tuple[TrialOutcome, ...]
    critical_escapes: int
    victory_conditions_violated: bool


def generate_match_id(
    scenario_id: str, *, now: datetime | None = None, unique: str | None = None
) -> str:
    """A stable, sortable, unique match id: `<UTC timestamp>-<scenario-id>-<suffix>`.

    The timestamp prefix makes match ids (and thus their output directories)
    sort chronologically on disk. The suffix is a `uuid4` hex fragment,
    guaranteeing uniqueness even for two matches of the same scenario started
    in the same second; it's overridable via `unique` for deterministic
    tests.
    """
    moment = now if now is not None else datetime.now(UTC)
    suffix = unique if unique is not None else uuid.uuid4().hex[:8]
    return f"{moment:%Y%m%dT%H%M%SZ}-{scenario_id}-{suffix}"


def select_agents(
    agent_registry: AgentRegistry, scenario_id: str, agent_id: str | None
) -> list[RegisteredAgent]:
    """Select agents compatible with `scenario_id`, optionally narrowed to one.

    Compatibility means the scenario id appears in the manifest's
    `scenarios` list (`AgentRegistry.filter(scenario=...)`). Results are
    sorted by agent id for deterministic iteration order.

    Raises:
        MatchOrchestrationError: `agent_id` is given but is not registered,
            or is registered but not compatible with `scenario_id`.
    """
    candidates = agent_registry.filter(scenario=scenario_id)
    if agent_id is not None:
        candidates = [a for a in candidates if a.manifest.id == agent_id]
        if not candidates:
            raise MatchOrchestrationError(
                f"agent {agent_id!r} is not registered or not compatible with "
                f"scenario {scenario_id!r}"
            )
    return sorted(candidates, key=lambda a: a.manifest.id)


def run_match(
    scenario_id: str,
    config: MatchConfig,
    *,
    agent_id: str | None = None,
    now: datetime | None = None,
) -> MatchResult:
    """Run a match: load the scenario, select agents, run every trial, emit events.

    Iterates agents (outer) x trials (inner) per AAASM-4373's scope, emitting
    `trial_started` / `agent_started` / `agent_finished` / `trial_finished`
    for every (agent, trial) pair, bracketed by one `match_started` and one
    `match_finished`.

    Raises:
        MatchOrchestrationError: the scenario id is unknown, no agents are
            registered/compatible, or agent/scenario loading fails.
    """
    try:
        scenario_registry = load_scenario_registry(config.scenarios_root)
    except ScenarioLoadError as exc:
        raise MatchOrchestrationError(str(exc)) from exc

    bundle = scenario_registry.get(scenario_id)
    if bundle is None:
        raise MatchOrchestrationError(
            f"scenario {scenario_id!r} not found under {config.scenarios_root}"
        )

    try:
        agent_registry = discover_agents(config.official_root, config.community_root)
    except RegistryLoadError as exc:
        raise MatchOrchestrationError(str(exc)) from exc

    selected = select_agents(agent_registry, scenario_id, agent_id)
    if not selected:
        raise MatchOrchestrationError(
            f"no registered agents are compatible with scenario {scenario_id!r}"
        )

    match_id = generate_match_id(scenario_id, now=now)
    workspace = config.output_root / match_id
    workspace.mkdir(parents=True, exist_ok=True)

    events: list[MatchEvent] = [
        MatchEvent(
            type=MatchEventType.MATCH_STARTED,
            match_id=match_id,
            timestamp=datetime.now(UTC),
            scenario_id=scenario_id,
            data={
                "agent_ids": ",".join(agent.manifest.id for agent in selected),
                "trial_count": len(bundle.trials),
            },
        )
    ]
    trial_outcomes: list[TrialOutcome] = []

    for agent in selected:
        for trial in bundle.trials:
            trial_workspace = workspace / agent.manifest.id / trial.id

            events.append(
                MatchEvent(
                    type=MatchEventType.TRIAL_STARTED,
                    match_id=match_id,
                    timestamp=datetime.now(UTC),
                    scenario_id=scenario_id,
                    agent_id=agent.manifest.id,
                    trial_id=trial.id,
                )
            )
            events.append(
                MatchEvent(
                    type=MatchEventType.AGENT_STARTED,
                    match_id=match_id,
                    timestamp=datetime.now(UTC),
                    scenario_id=scenario_id,
                    agent_id=agent.manifest.id,
                    trial_id=trial.id,
                )
            )

            runner = config.runner_registry.resolve(agent.manifest)
            error: str | None = None
            try:
                result = runner.run(agent.manifest, trial, workspace=trial_workspace)
            except (
                Exception
            ) as exc:  # a Runner must never crash the match; see Runner.run docstring
                error = str(exc)
                result = AgentRunResult(exit_code=1, stdout="", stderr=error, duration_seconds=0.0)

            passed = error is None and result.exit_code == 0
            trial_outcomes.append(
                TrialOutcome(
                    trial=trial,
                    agent_id=agent.manifest.id,
                    result=result,
                    passed=passed,
                    error=error,
                )
            )

            finished_data: dict[str, str | int | float | bool | None] = {
                "exit_code": result.exit_code,
                "duration_seconds": result.duration_seconds,
                "passed": passed,
            }
            if error is not None:
                finished_data["error"] = error

            events.append(
                MatchEvent(
                    type=MatchEventType.AGENT_FINISHED,
                    match_id=match_id,
                    timestamp=datetime.now(UTC),
                    scenario_id=scenario_id,
                    agent_id=agent.manifest.id,
                    trial_id=trial.id,
                    data=finished_data,
                )
            )
            events.append(
                MatchEvent(
                    type=MatchEventType.TRIAL_FINISHED,
                    match_id=match_id,
                    timestamp=datetime.now(UTC),
                    scenario_id=scenario_id,
                    agent_id=agent.manifest.id,
                    trial_id=trial.id,
                )
            )

    critical_escapes = sum(
        1 for outcome in trial_outcomes if not outcome.passed and outcome.trial.is_critical_escape
    )
    victory_conditions_violated = (
        critical_escapes > bundle.scenario.victory_conditions.critical_escapes
    )

    events.append(
        MatchEvent(
            type=MatchEventType.MATCH_FINISHED,
            match_id=match_id,
            timestamp=datetime.now(UTC),
            scenario_id=scenario_id,
            data={
                "critical_escapes": critical_escapes,
                "victory_conditions_violated": victory_conditions_violated,
                "trials_run": len(trial_outcomes),
            },
        )
    )

    return MatchResult(
        match_id=match_id,
        scenario=bundle.scenario,
        workspace=workspace,
        events=tuple(events),
        trial_outcomes=tuple(trial_outcomes),
        critical_escapes=critical_escapes,
        victory_conditions_violated=victory_conditions_violated,
    )
