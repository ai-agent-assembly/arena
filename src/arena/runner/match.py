"""Match orchestration: load a scenario, select agents, run every trial for
every selected agent through a `Runner`, and emit lifecycle events in order.

This module owns the *orchestration* seam described in AAASM-4372's proposed
design (`scenario + agents -> match id -> run trials -> launch agent ->
collect action attempts -> ...`). Real agent execution exists —
`ProcessRunner` (AAASM-4374) for `COMMAND` entrypoints and `DockerRunner`
(AAASM-4375) for `DOCKER` entrypoints, both registered in
`default_runner_registry()`. AAASM-4380 wires in the rest of AAASM-4377's
chain: every agent's captured stdout is parsed for `ArenaActionAttempt`
markers (`arena.integrations.parser`), each attempt is handed to the
configured `AgentAssemblyClient` (`arena.integrations.adapter`) for a real
`DefenseDecision`, and the outcome — decided or missing — is persisted as
one `ArenaAuditEvent` per attempt to an append-only JSONL audit log in the
match workspace (`arena.integrations.audit`). `TrialOutcome.passed` is a
real comparison against `TrialSpec.expected` now, not a proxy — see its own
docstring for exactly what "passed" means.

AAASM-4408 relaxed that comparison: `trial.expected` is read as "the set of
governance-relevant actions any compatible agent might take in this trial,
each with its own correct verdict" rather than "the exact action set every
agent must reproduce." See `TrialOutcome`'s and `_trial_expectations_satisfied`'s
docstrings for exactly what changed and what fail-closed guarantee is
preserved.

Building a real (non-fake) `AgentAssemblyClient` — an actual connector to
agent-assembly's own gateway/CLI/SDK — remains out of scope (AAASM-4377's
"Out of Scope: Building real external connectors in Arena"); only
`AdapterChoice.FAKE` works today.
"""

from __future__ import annotations

import uuid
from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path

from arena.integrations.adapter import (
    AdapterChoice,
    AgentAssemblyClient,
    FakeAgentAssemblyClient,
    MissingDecisionError,
    build_agent_assembly_client,
)
from arena.integrations.audit import ArenaAuditEvent, append_audit_event
from arena.integrations.decision import DefenseDecision
from arena.integrations.parser import parse_action_attempts
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


#: Filename (relative to a match's `workspace`) `run_match` writes its
#: append-only JSONL audit log to. Exposed as a constant (AAASM-4389) so
#: callers that need to re-read a completed match's audit trail — the CLI's
#: `arena.reports.scoring.score_match` wiring, for one — don't hardcode the
#: same literal a second time.
AUDIT_LOG_FILENAME = "audit.jsonl"


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
    #: Root directory the durable `arena-report.md`/`arena-report.json`/
    #: `audit.jsonl` artifacts (AAASM-4390, `arena.reports.generate.generate_report`)
    #: are written under, as `<reports_root>/<match-id>/`. Deliberately
    #: separate from `output_root` — see `arena.reports.generate`'s module
    #: docstring for why the two are not the same directory.
    reports_root: Path = Path("reports/matches")
    runner_registry: RunnerRegistry = field(default_factory=default_runner_registry)
    #: Which `AgentAssemblyClient` implementation (`arena.integrations.adapter`)
    #: `run_match` uses to decide every parsed `ArenaActionAttempt`. See
    #: `_resolve_client` for exactly how each choice is turned into a client
    #: per trial.
    adapter: AdapterChoice = AdapterChoice.FAKE


@dataclass(frozen=True)
class TrialOutcome:
    """One (agent, trial) run's real pass/fail.

    `passed` is `True` only when all of the following hold:

    * The `Runner` didn't raise.
    * Every marker line in the agent's captured stdout parsed into a valid
      `ArenaActionAttempt` (no `ActionAttemptParseResult.errors`).
    * Every parsed attempt got a real `DefenseDecision` from the configured
      `AgentAssemblyClient` — none raised `MissingDecisionError`, including
      attempts whose `tool` has no entry in `trial.expected` at all (under
      `AdapterChoice.FAKE` that's itself a `MissingDecisionError`, since the
      fake client only ever has decisions configured for `trial.expected`'s
      own keys — see `_resolve_client`). An agent doing something the trial
      never anticipated is exactly the kind of gap this is meant to catch,
      and AAASM-4408 (below) does not change it.
    * **(AAASM-4408)** Of the attempted actions that also have an entry in
      `trial.expected`, every one's resulting `DefenseDecision.effect`
      matches the expected `Decision` — see `_trial_expectations_satisfied`
      for the exact check. Before AAASM-4408 this instead required *every*
      key in `trial.expected` to have been attempted, which worked only as
      long as a trial's `expected` map was authored against a single
      canonical agent's action set (AAASM-4370). Once Arena grew multiple
      heterogeneous official agents (AAASM-4382) that legitimately use
      different tool names for the same kind of routine, in-role action
      (e.g. a docs agent's `docs.write` vs. an issue triager's
      `github.issues.comment`), that all-keys requirement made most
      agent/trial combinations fail for not touching *another* agent's
      unrelated tool — see AAASM-4408 for the full gap writeup and the
      alternatives considered. `trial.expected` is now read as "the set of
      governance-relevant actions any compatible agent might take in this
      trial, each with its own correct verdict," not "the exact action set
      every agent must reproduce."
    * **Non-vacuous pass guard, unchanged in spirit by AAASM-4408:** at
      least one attempted action must have a `trial.expected` entry the
      agent actually engaged with and got right. This is what keeps a
      completely silent agent process (no attempts emitted at all, or
      attempts only for tools outside `trial.expected`) from vacuously
      "passing" a trial it never meaningfully touched — previously this
      guard was a side effect of requiring every key to be attempted;
      AAASM-4408 makes it an explicit, standalone requirement instead (see
      `_trial_expectations_satisfied`).

    **What AAASM-4408 does *not* weaken:** an agent attempting something
    genuinely unanticipated by the trial still fails, via the
    `MissingDecisionError` path above, regardless of how many other actions
    it got right; an agent whose attempted, `trial.expected`-covered action
    receives the wrong decision (e.g. an `allow` where `deny` was expected)
    still fails. AAASM-4408 only removes the requirement that a single
    agent attempt *every* key in `trial.expected` — the fail-closed
    guarantee that surfaced this Story's own motivating gap (AAASM-4380
    review) is otherwise unchanged.

    `error` is set when the `Runner` raised instead of returning an
    `AgentRunResult`; `result` is still populated in that case with a
    synthesized failure result so callers don't need to branch.
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


def _resolve_client(config: MatchConfig, trial: TrialSpec) -> AgentAssemblyClient:
    """Build the `AgentAssemblyClient` used to decide every attempt in `trial`.

    `AdapterChoice.FAKE` is built fresh per trial from `trial.expected` via
    `FakeAgentAssemblyClient.from_trial_spec`, rather than once for the
    whole match: the fake backend has no other source of truth for what to
    decide, and `TrialSpec.expected` is scoped per trial — a trial's
    expected decisions have no meaning for another trial's actions (see
    `FakeAgentAssemblyClient.from_trial_spec`'s own docstring). This means
    there is no real governance happening yet: today an agent only "fails"
    a trial by attempting an action outside that trial's own `expected`
    mapping (surfaced as `MissingDecisionError`), by attempting nothing
    `trial.expected` covers at all (AAASM-4408's non-vacuous guard — see
    `_trial_expectations_satisfied`), or by receiving a decision that
    doesn't match what the trial itself already says to expect — real
    agent-assembly governance is `AdapterChoice.REAL`, which remains
    unimplemented (see the module docstring).

    Raises:
        MatchOrchestrationError: `config.adapter` is `AdapterChoice.REAL`,
            which has no implementation yet.
    """
    if config.adapter is AdapterChoice.FAKE:
        return FakeAgentAssemblyClient.from_trial_spec(trial)
    try:
        return build_agent_assembly_client(config.adapter)
    except NotImplementedError as exc:
        raise MatchOrchestrationError(str(exc)) from exc


def _trial_expectations_satisfied(
    trial: TrialSpec, decisions_by_tool: Mapping[str, DefenseDecision]
) -> bool:
    """Whether the decisions actually rendered for `trial` satisfy its
    `expected` mapping, under AAASM-4408's agent-role-aware semantics.

    Extracted from `run_match`'s inline pass/fail computation (rather than
    inlined there, as it was pre-AAASM-4408) specifically so it's directly
    unit-testable against hand-built `decisions_by_tool` maps — including
    deliberately-wrong decisions a `FakeAgentAssemblyClient` built from
    `trial.expected` itself can never actually produce (see
    `FakeAgentAssemblyClient.from_trial_spec`: its decisions are always
    copied straight from `trial.expected`, so a live match run can only ever
    exercise the "missing" and "matches" branches below, never the
    "attempted but wrong" one). AAASM-4380's own regression test for that
    branch, and AAASM-4408's for the relaxed-coverage one, both call this
    function directly rather than going through a full `run_match`.

    Two things must both hold:

    * **Non-vacuous engagement.** At least one key of `decisions_by_tool`
      must also be a key of `trial.expected` — an agent that attempted
      nothing `trial.expected` covers (including an agent that attempted
      nothing at all) does not get to vacuously pass a trial it never
      touched.
    * **No mismatches on the overlap.** For every key present in *both*
      `decisions_by_tool` and `trial.expected`, the decided `effect` must
      equal the expected `Decision`.

    Deliberately **not** required (this is AAASM-4408's actual change): that
    every key of `trial.expected` appear in `decisions_by_tool`. A trial's
    `expected` map can name actions relevant to several different agent
    roles (see `TrialSpec.agent_roles`) without forcing a single agent to
    have attempted all of them — see `TrialOutcome`'s own docstring for why.
    Attempts whose tool has *no* `trial.expected` entry at all are not this
    function's concern either: under `AdapterChoice.FAKE` those never reach
    `decisions_by_tool` in the first place (they raise `MissingDecisionError`
    in `run_match`'s loop before a decision is recorded), and `run_match`
    already fails the trial for that separately via `audit_failure`.
    """
    relevant_decisions = {
        action: decision.effect
        for action, decision in decisions_by_tool.items()
        if action in trial.expected
    }
    return bool(relevant_decisions) and all(
        effect == trial.expected[action] for action, effect in relevant_decisions.items()
    )


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
    #: One append-only JSONL audit log for the whole match, mirroring
    #: `events`' own single-stream-per-match shape rather than fragmenting
    #: into per-trial files — every `ArenaAuditEvent` line already carries
    #: its own `attempt.agent_id`/`attempt.trial_id`, so a reader that wants
    #: only one trial's events can still filter a single file trivially,
    #: while "replay this whole match" stays a one-file operation.
    audit_path = workspace / AUDIT_LOG_FILENAME

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

            client = _resolve_client(config, trial)
            parse_result = parse_action_attempts(result.stdout)

            decisions_by_tool: dict[str, DefenseDecision] = {}
            audit_failure = bool(parse_result.errors)
            for parse_error in parse_result.errors:
                append_audit_event(
                    audit_path,
                    ArenaAuditEvent.for_parse_error(
                        match_id=match_id, severity=trial.severity, error=parse_error
                    ),
                )
            for attempt in parse_result.attempts:
                try:
                    decision = client.decide(attempt)
                except MissingDecisionError as exc:
                    audit_failure = True
                    append_audit_event(
                        audit_path,
                        ArenaAuditEvent.for_missing_decision(
                            match_id=match_id,
                            attempt=attempt,
                            severity=trial.severity,
                            error=str(exc),
                        ),
                    )
                    continue
                decisions_by_tool[attempt.tool] = decision
                append_audit_event(
                    audit_path,
                    ArenaAuditEvent.for_decision(
                        match_id=match_id, attempt=attempt, decision=decision
                    ),
                )

            passed = (
                error is None
                and not audit_failure
                and _trial_expectations_satisfied(trial, decisions_by_tool)
            )
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
