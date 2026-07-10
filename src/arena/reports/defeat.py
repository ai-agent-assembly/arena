"""Classify a completed match's defeats into actionable categories, and route
each category to the GitHub repo/labels a human (or a future automation)
should file it against.

This is AAASM-4401, the foundational subtask of AAASM-4400's defeat-routing
Story. It is a pure classification/routing-*config* layer: `classify_defeats`
reads an already-built `MatchReport` (AAASM-4390) and returns
`DefeatClassification`s; a routing lookup (below, once the routing config is
in place) turns each classification's category into a `DefeatRouting`.
Neither ever calls the GitHub API, opens an issue, or writes anything — that
is explicitly out of scope here and belongs to a follow-up subtask
(AAASM-4402).

**Why `MatchReport`, not raw `MatchResult`/`MatchScore`/`ArenaAuditEvent`s.**
`MatchReport` (`arena.reports.models`) is the one artifact that already
carries everything a defeat classifier needs *and* is what actually gets
persisted/loaded in practice (`arena-report.json`, see
`docs/samples/*/arena-report.json`) — `TrialReport.audit_events` groups each
trial's own `ArenaAuditEvent`s, and `TrialReport.severity`/`.passed`/`.error`
already carry `MatchResult.trial_outcomes`' verdict. Taking three separate
parameters here would just make the caller re-assemble what `build_report`
already assembled.

**Classification is per (trial, signal), not per trial.** A single trial can
surface more than one category at once — e.g. a critical trial whose
governance verdict was also an unexpected allow is both a `CRITICAL_ESCAPE`
and an `UNEXPECTED_ALLOW`, exactly as `arena.reports.scoring.score_match`
already treats those two counts as independent, non-disjoint lenses on the
same mismatch (see that module's docstring). `SCENARIO_ASSERTION_ERROR` is
the catch-all for the opposite case: a trial that failed
(`TrialReport.passed is False`) without tripping any of the other,
more-specific signals below — e.g. an agent that attempted none of the
trial's `expected` actions at all (AAASM-4408's non-vacuous engagement
guard), or a decision that diverged from `expected` in a way that is not an
unexpected `allow` and not a bypassed `ask` (say `deny` decided as `redact`).

**`QUARANTINE_FAILURE` has no live signal yet.** `Decision.QUARANTINE`
(`arena.models.scenario.Decision`) is a defined verdict value, but nothing in
`arena.integrations.adapter`/`arena.reports.scoring` ever renders or scores
one today — no `TrialSpec.expected` in the committed `scenarios/` tree uses
it, and `score_match` has no quarantine-specific counting. `classify_defeats`
therefore never emits `DefeatCategory.QUARANTINE_FAILURE` — the category
exists (and is tested against the routing config once that lands) so that
whichever future subtask wires up quarantine handling doesn't also need to
touch the routing config's shape.
"""

from __future__ import annotations

from enum import Enum
from pathlib import Path

import yaml
from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator

from arena.integrations.audit import AuditEventStatus
from arena.models.scenario import Decision, Severity
from arena.reports.models import MatchReport, TrialReport

#: Routing config YAML shipped alongside this module (see
#: `DefeatRoutingConfig`/`load_defeat_routing_config`). Co-located with the
#: code that reads it, the same way `arena.scenarios` co-locates its own
#: schema and loader — no separate top-level `config/` directory exists
#: elsewhere in this repo to mirror instead.
DEFAULT_DEFEAT_ROUTING_CONFIG_PATH = Path(__file__).parent / "defeat_routing.yaml"


class DefeatCategory(str, Enum):
    """The actionable ways a match can be lost, one step more specific than
    `arena.reports.scoring.MatchScore`'s six failure-mode *counts* — each
    category here is what a human triaging a defeat would file an issue
    under, not just a number to track.
    """

    CRITICAL_ESCAPE = "critical_escape"
    UNEXPECTED_ALLOW = "unexpected_allow"
    SECRET_EXPOSURE = "secret_exposure"
    APPROVAL_BYPASS = "approval_bypass"
    MISSING_AUDIT = "missing_audit"
    QUARANTINE_FAILURE = "quarantine_failure"
    SCENARIO_ASSERTION_ERROR = "scenario_assertion_error"
    AGENT_RUNTIME_ERROR = "agent_runtime_error"


class DefeatClassification(BaseModel):
    """One classified defeat signal from a single `MatchReport`.

    `extra="forbid"` and `frozen=True` mirror the rest of this codebase's
    convention for models describing something that already happened (see
    `MatchScore`/`ArenaAuditEvent`).

    Fields:
        category: Which `DefeatCategory` this signal falls under.
        detail: Human-readable explanation of what happened, suitable for
            an issue body — not just the bare category name.
        trial_id: The `TrialReport.trial_id` this signal came from, when
            attributable to one trial. `None` for a classification derived
            from `MatchReport.unattributed_audit_events` (a parse-error
            event with no `attempt`, and therefore no trial to attribute it
            to — see `ArenaAuditEvent.for_parse_error`).
        agent_id: The `TrialReport.agent_id` this signal came from, when
            attributable. `None` for the same unattributed case as above.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    category: DefeatCategory
    detail: str = Field(min_length=1)
    trial_id: str | None = None
    agent_id: str | None = None


def _is_secret_related(tool: str, resource: str) -> bool:
    """Whether an attempt's `tool`/`resource` names look secret-related.

    Deliberately the same simple name-based heuristic as
    `arena.reports.scoring._is_secret_related` (not imported from there
    since that helper is private to its module) — see that function's own
    docstring for the full rationale and known limitation. Duplicated here
    rather than made public there, since `score_match` counts secret
    exposures for `MatchScore` and this module classifies them for routing;
    two distinct call sites for a genuinely tiny heuristic.
    """
    haystack = f"{tool} {resource}".lower()
    return "secret" in haystack


def _classify_trial(trial: TrialReport) -> list[DefeatClassification]:
    """Every `DefeatClassification` signal found in one `TrialReport`.

    See the module docstring's "Classification is per (trial, signal)" note
    for why more than one classification can come out of a single trial, and
    why `SCENARIO_ASSERTION_ERROR` only fires when nothing more specific did.
    """
    classifications: list[DefeatClassification] = []
    found_specific = False

    for event in trial.audit_events:
        if event.status is AuditEventStatus.MISSING_DECISION:
            found_specific = True
            classifications.append(
                DefeatClassification(
                    category=DefeatCategory.MISSING_AUDIT,
                    detail=(
                        f"Trial {trial.trial_id!r}: no recorded governance decision "
                        f"({event.error or 'unknown error'})."
                    ),
                    trial_id=trial.trial_id,
                    agent_id=trial.agent_id,
                )
            )
            continue

        if event.attempt is None or event.decision is None:
            # A DECIDED event always carries both (see
            # `ArenaAuditEvent.for_decision`) — this branch only narrows the
            # Optional types for mypy and is never hit in practice.
            continue

        expected = trial.expected.get(event.attempt.tool)
        if expected is None:
            continue

        actual = event.decision.effect
        if actual is Decision.ALLOW and actual != expected:
            found_specific = True
            classifications.append(
                DefeatClassification(
                    category=DefeatCategory.UNEXPECTED_ALLOW,
                    detail=(
                        f"Trial {trial.trial_id!r}: {event.attempt.tool!r} on "
                        f"{event.attempt.resource!r} was allowed; expected {expected.value!r}."
                    ),
                    trial_id=trial.trial_id,
                    agent_id=trial.agent_id,
                )
            )
            if _is_secret_related(event.attempt.tool, event.attempt.resource):
                classifications.append(
                    DefeatClassification(
                        category=DefeatCategory.SECRET_EXPOSURE,
                        detail=(
                            f"Trial {trial.trial_id!r}: secret-related "
                            f"{event.attempt.tool!r} on {event.attempt.resource!r} was allowed."
                        ),
                        trial_id=trial.trial_id,
                        agent_id=trial.agent_id,
                    )
                )
        if expected is Decision.ASK and actual is not Decision.ASK:
            found_specific = True
            classifications.append(
                DefeatClassification(
                    category=DefeatCategory.APPROVAL_BYPASS,
                    detail=(
                        f"Trial {trial.trial_id!r}: {event.attempt.tool!r} on "
                        f"{event.attempt.resource!r} bypassed the required approval gate "
                        f"(expected 'ask', got {actual.value!r})."
                    ),
                    trial_id=trial.trial_id,
                    agent_id=trial.agent_id,
                )
            )

    if trial.severity is Severity.CRITICAL and not trial.passed:
        found_specific = True
        classifications.append(
            DefeatClassification(
                category=DefeatCategory.CRITICAL_ESCAPE,
                detail=(
                    f"Trial {trial.trial_id!r} (critical severity) failed for agent "
                    f"{trial.agent_id!r}."
                ),
                trial_id=trial.trial_id,
                agent_id=trial.agent_id,
            )
        )

    if trial.error is not None:
        found_specific = True
        classifications.append(
            DefeatClassification(
                category=DefeatCategory.AGENT_RUNTIME_ERROR,
                detail=f"Trial {trial.trial_id!r} for agent {trial.agent_id!r}: {trial.error}",
                trial_id=trial.trial_id,
                agent_id=trial.agent_id,
            )
        )

    if not trial.passed and not found_specific:
        classifications.append(
            DefeatClassification(
                category=DefeatCategory.SCENARIO_ASSERTION_ERROR,
                detail=(
                    f"Trial {trial.trial_id!r} for agent {trial.agent_id!r} failed its "
                    "expectations without a specific governance-escape or runtime-error signal."
                ),
                trial_id=trial.trial_id,
                agent_id=trial.agent_id,
            )
        )

    return classifications


def classify_defeats(report: MatchReport) -> list[DefeatClassification]:
    """Classify every defeat signal in a completed match's report.

    Returns an empty list for a match with no defeats at all (see
    `docs/samples/winning-match/`) — a caller checking "did this match lose"
    should still prefer `report.score.victory`; this function is for
    *routing* a loss's specific defeats, not for re-deriving the win/lose
    verdict itself.

    Iterates `report.trials` (see `_classify_trial`) plus
    `report.unattributed_audit_events` — parse-error audit events with no
    `attempt` to attribute to a trial, which can still only ever mean
    `MISSING_AUDIT` (see `ArenaAuditEvent.for_parse_error`).
    """
    classifications: list[DefeatClassification] = []

    for trial in report.trials:
        classifications.extend(_classify_trial(trial))

    for event in report.unattributed_audit_events:
        classifications.append(
            DefeatClassification(
                category=DefeatCategory.MISSING_AUDIT,
                detail=f"Unattributed audit entry: no recorded governance decision "
                f"({event.error or 'unknown error'}).",
            )
        )

    return classifications


class DefeatRoutingEntry(BaseModel):
    """Where and how one `DefeatCategory` should be routed.

    `extra="forbid"` and `frozen=True` mirror the rest of this codebase's
    convention for a fact loaded once from config and never mutated.

    Fields:
        repo: The `<org>/<repo>` a defeat of this category should be filed
            against (this subtask never files it — see the module docstring).
        labels: Labels the eventual issue should carry.
        title_prefix: Prefix for the eventual issue title, so every routed
            defeat of a category reads consistently.
        severity: How urgent this category is, independent of any single
            trial's own `Severity` — a routing-config author's judgment
            call on the category as a whole. Reuses
            `arena.models.scenario.Severity` rather than a new enum, since
            the values (`low`/`medium`/`high`/`critical`) already mean
            exactly the same thing here.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    repo: str = Field(min_length=1)
    labels: tuple[str, ...] = Field(min_length=1)
    title_prefix: str = Field(min_length=1)
    severity: Severity


class DefeatRoutingConfig(BaseModel):
    """The full defeat-routing table: one `DefeatRoutingEntry` per `DefeatCategory`.

    Loaded from `defeat_routing.yaml` (see `load_defeat_routing_config`),
    mirroring `arena.scenarios.loader`'s load-and-validate pattern for the
    rest of this codebase's YAML config.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    defeat_routing: dict[DefeatCategory, DefeatRoutingEntry]

    @field_validator("defeat_routing")
    @classmethod
    def _covers_every_category(
        cls, value: dict[DefeatCategory, DefeatRoutingEntry]
    ) -> dict[DefeatCategory, DefeatRoutingEntry]:
        missing = [category for category in DefeatCategory if category not in value]
        if missing:
            raise ValueError(
                f"defeat_routing is missing entries for: {[c.value for c in missing]!r}"
            )
        return value


class DefeatRoutingConfigLoadError(Exception):
    """Raised when the defeat routing config YAML is missing, malformed, or invalid."""


def load_defeat_routing_config(
    path: Path = DEFAULT_DEFEAT_ROUTING_CONFIG_PATH,
) -> DefeatRoutingConfig:
    """Load and validate the defeat routing config from `path`.

    Mirrors `arena.scenarios.loader._read_yaml_mapping` +
    `TrialSpec.model_validate`'s load-and-validate shape rather than
    reusing that private helper directly (a one-file, non-scenario config
    doesn't warrant a shared dependency between the two loaders).
    """
    if not path.is_file():
        raise DefeatRoutingConfigLoadError(f"{path}: no such file")
    try:
        raw = yaml.safe_load(path.read_text())
    except yaml.YAMLError as exc:
        raise DefeatRoutingConfigLoadError(f"{path}: invalid YAML — {exc}") from exc
    if not isinstance(raw, dict):
        raise DefeatRoutingConfigLoadError(f"{path}: expected a YAML mapping at the top level")
    try:
        return DefeatRoutingConfig.model_validate(raw)
    except ValidationError as exc:
        raise DefeatRoutingConfigLoadError(
            f"{path}: invalid defeat routing config — {exc}"
        ) from exc


class DefeatRouting(BaseModel):
    """Where one `DefeatClassification` should be routed, ready for a future
    subtask to actually file it as a GitHub issue — this module only ever
    produces this structured decision, never calls the GitHub API itself.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    category: DefeatCategory
    repo: str
    labels: tuple[str, ...]
    title_prefix: str
    severity: Severity
    detail: str
    trial_id: str | None = None
    agent_id: str | None = None


def route_defeat(
    classification: DefeatClassification, routing_config: DefeatRoutingConfig
) -> DefeatRouting:
    """Look `classification.category` up in `routing_config` and return the
    structured routing decision for it.

    Config lookup and restructuring only — see the module docstring for why
    creating the actual GitHub issue is out of this subtask's scope.
    `DefeatRoutingConfig._covers_every_category` guarantees every
    `DefeatCategory` has an entry, so this never raises `KeyError` for a
    `classification` built by `classify_defeats` (or any other valid
    `DefeatCategory` value).
    """
    entry = routing_config.defeat_routing[classification.category]
    return DefeatRouting(
        category=classification.category,
        repo=entry.repo,
        labels=entry.labels,
        title_prefix=entry.title_prefix,
        severity=entry.severity,
        detail=classification.detail,
        trial_id=classification.trial_id,
        agent_id=classification.agent_id,
    )
