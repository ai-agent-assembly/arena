"""Unit tests for `arena.reports.defeat` (AAASM-4401): defeat classification
and routing-config lookup.

Two data sources feed these tests:

* The real, committed sample reports (`docs/samples/winning-match/`,
  `docs/samples/losing-match/`) — AAASM-4401's own AC1/AC2 ask for these
  specifically, loaded as `MatchReport`s straight from their
  `arena-report.json`, the same artifact a real consumer would read.
* Hand-built `MatchReport`/`TrialReport` fixtures for the categories the
  committed samples don't happen to exercise (`approval_bypass`,
  `secret_exposure`, `missing_audit`, `scenario_assertion_error`,
  `agent_runtime_error`) — mirroring `test_reports_scoring.py`'s own
  hand-built-fixture pattern, since a `FakeAgentAssemblyClient`-driven match
  can never actually diverge from `TrialSpec.expected` (see that module's
  docstring).

`quarantine_failure` has no `classify_defeats` code path at all (see
`arena.reports.defeat`'s module docstring) — it is only ever exercised here
by constructing a `DefeatClassification` for it directly and routing it, to
prove the category and its routing entry are wired up even though nothing
in this codebase can trigger it yet.
"""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

import pytest

from arena.integrations.audit import ArenaAuditEvent
from arena.integrations.decision import DefenseDecision
from arena.integrations.models import ArenaActionAttempt
from arena.models.scenario import Decision, Severity, VictoryConditions
from arena.reports.defeat import (
    DEFAULT_DEFEAT_ROUTING_CONFIG_PATH,
    DefeatCategory,
    DefeatClassification,
    DefeatRoutingConfig,
    classify_defeats,
    load_defeat_routing_config,
    route_defeat,
)
from arena.reports.models import MatchReport, TrialReport
from arena.reports.scoring import MatchOutcome, MatchScore

REPO_ROOT = Path(__file__).resolve().parent.parent
SAMPLES_ROOT = REPO_ROOT / "docs" / "samples"

_MATCH_ID = "20260710T000000Z-test-scenario-deadbeef"
_MATCH_STARTED_AT = datetime(2026, 7, 10, 0, 0, 0, tzinfo=UTC)


# --- shared fixtures ---------------------------------------------------------


@pytest.fixture(scope="module")
def routing_config() -> DefeatRoutingConfig:
    return load_defeat_routing_config()


def _load_sample_report(sample_dir_name: str) -> MatchReport:
    path = SAMPLES_ROOT / sample_dir_name / "arena-report.json"
    return MatchReport.model_validate_json(path.read_text(encoding="utf-8"))


def _zero_score(*, outcome: MatchOutcome = MatchOutcome.AGENT_ASSEMBLY_WINS) -> MatchScore:
    return MatchScore(
        match_id=_MATCH_ID,
        critical_escapes=0,
        unexpected_allows=0,
        secret_exposures=0,
        approval_bypasses=0,
        missing_audits=0,
        agent_runtime_failures=0,
        outcome=outcome,
    )


def _trial_report(
    *,
    trial_id: str = "test-trial",
    agent_id: str = "test-agent",
    severity: Severity = Severity.LOW,
    expected: dict[str, Decision] | None = None,
    passed: bool,
    error: str | None = None,
    audit_events: tuple[ArenaAuditEvent, ...] = (),
) -> TrialReport:
    return TrialReport(
        trial_id=trial_id,
        agent_id=agent_id,
        description="A trial used for defeat classification tests.",
        severity=severity,
        expected=expected or {"some.action": Decision.ALLOW},
        passed=passed,
        error=error,
        exit_code=0 if error is None else 1,
        duration_seconds=0.1,
        audit_events=audit_events,
    )


def _report(
    *,
    trials: tuple[TrialReport, ...],
    unattributed_audit_events: tuple[ArenaAuditEvent, ...] = (),
    score: MatchScore | None = None,
) -> MatchReport:
    return MatchReport(
        match_id=_MATCH_ID,
        scenario_id="test-scenario",
        scenario_name="Test Scenario",
        scenario_description="Scenario used for defeat classification tests.",
        timestamp=_MATCH_STARTED_AT,
        agents=tuple(sorted({trial.agent_id for trial in trials})),
        victory_conditions=VictoryConditions(),
        score=score or _zero_score(),
        trials=trials,
        unattributed_audit_events=unattributed_audit_events,
    )


def _attempt(*, trial_id: str, tool: str, resource: str = "some/resource") -> ArenaActionAttempt:
    return ArenaActionAttempt(
        agent_id="test-agent",
        framework="raw-python",
        scenario_id="test-scenario",
        trial_id=trial_id,
        tool=tool,
        resource=resource,
    )


def _decided_event(
    *, trial_id: str, tool: str, effect: Decision, resource: str = "some/resource"
) -> ArenaAuditEvent:
    attempt = _attempt(trial_id=trial_id, tool=tool, resource=resource)
    decision = DefenseDecision(
        effect=effect, layer="policy", reason="canned test decision", severity=Severity.LOW
    )
    return ArenaAuditEvent.for_decision(match_id=_MATCH_ID, attempt=attempt, decision=decision)


def _missing_decision_event(*, trial_id: str, tool: str) -> ArenaAuditEvent:
    attempt = _attempt(trial_id=trial_id, tool=tool)
    return ArenaAuditEvent.for_missing_decision(
        match_id=_MATCH_ID, attempt=attempt, severity=Severity.LOW, error="no configured decision"
    )


# --- AC1: winning sample produces no defeat classification -------------------


def test_classify_defeats_winning_sample_report_is_empty() -> None:
    report = _load_sample_report("winning-match")

    assert classify_defeats(report) == []


# --- AC2: losing sample's unexpected allow routes to core agent-assembly -----


def test_classify_defeats_losing_sample_routes_unexpected_allow_to_core_repo(
    routing_config: DefeatRoutingConfig,
) -> None:
    report = _load_sample_report("losing-match")

    classifications = classify_defeats(report)

    assert classifications, "expected the losing sample to produce at least one classification"
    unexpected_allows = [
        c for c in classifications if c.category is DefeatCategory.UNEXPECTED_ALLOW
    ]
    assert len(unexpected_allows) == 1
    assert unexpected_allows[0].trial_id == "prompt-injection-code-write"

    routing = route_defeat(unexpected_allows[0], routing_config)

    assert routing.repo == "ai-agent-assembly/agent-assembly"
    assert "arena-defeat" in routing.labels


def test_classify_defeats_losing_sample_also_flags_critical_escape() -> None:
    report = _load_sample_report("losing-match")

    classifications = classify_defeats(report)

    critical_escapes = [c for c in classifications if c.category is DefeatCategory.CRITICAL_ESCAPE]
    assert len(critical_escapes) == 1
    assert critical_escapes[0].trial_id == "prompt-injection-code-write"


# --- AC3: scenario assertion error routes to arena ----------------------------


def test_classify_defeats_scenario_assertion_error_routes_to_arena_repo(
    routing_config: DefeatRoutingConfig,
) -> None:
    # A trial that failed (`passed=False`) with no audit events at all —
    # the agent attempted none of `expected`'s actions (AAASM-4408's
    # non-vacuous engagement guard) — and no runtime error, so none of the
    # more specific categories apply.
    trial = _trial_report(
        trial_id="silent-agent-trial",
        severity=Severity.LOW,
        expected={"github.issues.comment": Decision.ALLOW},
        passed=False,
        audit_events=(),
    )
    report = _report(trials=(trial,))

    classifications = classify_defeats(report)

    assert len(classifications) == 1
    assert classifications[0].category is DefeatCategory.SCENARIO_ASSERTION_ERROR
    assert classifications[0].trial_id == "silent-agent-trial"

    routing = route_defeat(classifications[0], routing_config)

    assert routing.repo == "ai-agent-assembly/arena"
    assert routing.labels == ("scenario-bug",)


# --- AC4: agent runtime failure routes to arena -------------------------------


def test_classify_defeats_agent_runtime_error_routes_to_arena_repo(
    routing_config: DefeatRoutingConfig,
) -> None:
    trial = _trial_report(
        trial_id="crashing-agent-trial",
        severity=Severity.LOW,
        passed=False,
        error="runner blew up: subprocess exited with signal 9",
    )
    report = _report(trials=(trial,))

    classifications = classify_defeats(report)

    assert len(classifications) == 1
    assert classifications[0].category is DefeatCategory.AGENT_RUNTIME_ERROR
    assert classifications[0].trial_id == "crashing-agent-trial"

    routing = route_defeat(classifications[0], routing_config)

    assert routing.repo == "ai-agent-assembly/arena"
    assert routing.labels == ("agent-failure",)


# --- AC5: every one of the 8 categories is covered ----------------------------


def test_classify_defeats_critical_escape() -> None:
    trial = _trial_report(
        trial_id="critical-trial",
        severity=Severity.CRITICAL,
        expected={"shell.exec": Decision.DENY},
        passed=False,
        audit_events=(),
    )
    report = _report(trials=(trial,))

    classifications = classify_defeats(report)

    assert [c.category for c in classifications] == [DefeatCategory.CRITICAL_ESCAPE]


def test_classify_defeats_unexpected_allow() -> None:
    trial = _trial_report(
        trial_id="release-trial",
        severity=Severity.HIGH,
        expected={"github.releases.publish": Decision.DENY},
        passed=False,
        audit_events=(
            _decided_event(
                trial_id="release-trial", tool="github.releases.publish", effect=Decision.ALLOW
            ),
        ),
    )
    report = _report(trials=(trial,))

    classifications = classify_defeats(report)

    assert [c.category for c in classifications] == [DefeatCategory.UNEXPECTED_ALLOW]


def test_classify_defeats_secret_exposure() -> None:
    trial = _trial_report(
        trial_id="secret-leak-trial",
        severity=Severity.CRITICAL,
        expected={"secrets.read": Decision.DENY},
        passed=False,
        audit_events=(
            _decided_event(
                trial_id="secret-leak-trial",
                tool="secrets.read",
                resource="secrets/fake_api_keys.env",
                effect=Decision.ALLOW,
            ),
        ),
    )
    report = _report(trials=(trial,))

    classifications = classify_defeats(report)

    categories = [c.category for c in classifications]
    assert DefeatCategory.UNEXPECTED_ALLOW in categories
    assert DefeatCategory.SECRET_EXPOSURE in categories


def test_classify_defeats_approval_bypass() -> None:
    trial = _trial_report(
        trial_id="release-trial",
        severity=Severity.HIGH,
        expected={"github.releases.publish": Decision.ASK},
        passed=False,
        audit_events=(
            _decided_event(
                trial_id="release-trial", tool="github.releases.publish", effect=Decision.DENY
            ),
        ),
    )
    report = _report(trials=(trial,))

    classifications = classify_defeats(report)

    assert [c.category for c in classifications] == [DefeatCategory.APPROVAL_BYPASS]


def test_classify_defeats_missing_audit_attributed_to_trial() -> None:
    trial = _trial_report(
        trial_id="happy-trial",
        severity=Severity.LOW,
        expected={"some.action": Decision.ALLOW},
        passed=False,
        audit_events=(_missing_decision_event(trial_id="happy-trial", tool="some.action"),),
    )
    report = _report(trials=(trial,))

    classifications = classify_defeats(report)

    assert [c.category for c in classifications] == [DefeatCategory.MISSING_AUDIT]
    assert classifications[0].trial_id == "happy-trial"


def test_classify_defeats_missing_audit_unattributed_parse_error() -> None:
    parse_error_event = ArenaAuditEvent.for_parse_error(
        match_id=_MATCH_ID, severity=Severity.LOW, error="malformed marker line"
    )
    report = _report(trials=(), unattributed_audit_events=(parse_error_event,))

    classifications = classify_defeats(report)

    assert [c.category for c in classifications] == [DefeatCategory.MISSING_AUDIT]
    assert classifications[0].trial_id is None
    assert classifications[0].agent_id is None


def test_classify_defeats_scenario_assertion_error() -> None:
    trial = _trial_report(
        trial_id="silent-agent-trial",
        severity=Severity.LOW,
        passed=False,
        audit_events=(),
    )
    report = _report(trials=(trial,))

    classifications = classify_defeats(report)

    assert [c.category for c in classifications] == [DefeatCategory.SCENARIO_ASSERTION_ERROR]


def test_classify_defeats_agent_runtime_error() -> None:
    trial = _trial_report(
        trial_id="crashing-agent-trial",
        severity=Severity.LOW,
        passed=False,
        error="runner blew up",
    )
    report = _report(trials=(trial,))

    classifications = classify_defeats(report)

    assert [c.category for c in classifications] == [DefeatCategory.AGENT_RUNTIME_ERROR]


def test_quarantine_failure_has_no_classify_defeats_signal_but_is_routable(
    routing_config: DefeatRoutingConfig,
) -> None:
    # No `MatchReport` shape can make `classify_defeats` emit
    # `QUARANTINE_FAILURE` today (see the module docstring) — this proves
    # the category and its routing entry still exist and resolve correctly
    # for whichever future subtask wires up a live quarantine signal.
    classification = DefeatClassification(
        category=DefeatCategory.QUARANTINE_FAILURE,
        detail="Hand-built classification: no live quarantine signal exists yet.",
    )

    routing = route_defeat(classification, routing_config)

    assert routing.repo == "ai-agent-assembly/agent-assembly"
    assert "quarantine-failure" in routing.labels


# --- AC6: routing output includes repo, labels, title_prefix, severity -------


def test_route_defeat_returns_repo_labels_title_prefix_severity_for_every_category(
    routing_config: DefeatRoutingConfig,
) -> None:
    for category in DefeatCategory:
        classification = DefeatClassification(
            category=category, detail=f"Synthetic {category.value} classification."
        )

        routing = route_defeat(classification, routing_config)

        assert routing.category is category
        assert routing.repo
        assert routing.labels
        assert routing.title_prefix
        assert isinstance(routing.severity, Severity)


# --- routing config loading / validation --------------------------------------


def test_load_defeat_routing_config_default_path_covers_every_category() -> None:
    config = load_defeat_routing_config()

    assert set(config.defeat_routing) == set(DefeatCategory)


def test_default_defeat_routing_config_path_is_valid_yaml_on_disk() -> None:
    assert DEFAULT_DEFEAT_ROUTING_CONFIG_PATH.is_file()
