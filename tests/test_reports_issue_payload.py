"""Unit tests for `arena.reports.issue_payload` (AAASM-4402): the GitHub
issue title/body payload built for one routed Arena defeat, plus its
duplicate-issue-prevention fingerprint.

Like `test_reports_defeat.py` (AAASM-4401), this uses two data sources:

* The real, committed sample reports (`docs/samples/winning-match/`,
  `docs/samples/losing-match/`) — AAASM-4402's own AC1/AC2 ask for these
  specifically.
* Hand-built `MatchReport`/`TrialReport` fixtures for cases the committed
  samples don't exercise (an unattributed `missing_audit` classification,
  fingerprint sensitivity to policy id).

Every test here is a pure function call against in-memory/on-disk fixtures —
no network access, no GitHub credentials — proving AC4 ("dry-run output is
testable without GitHub credentials").
"""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

from arena.integrations.audit import ArenaAuditEvent
from arena.integrations.decision import DefenseDecision
from arena.integrations.models import ArenaActionAttempt
from arena.models.scenario import Decision, Severity, VictoryConditions
from arena.reports.defeat import (
    DefeatCategory,
    DefeatClassification,
    classify_defeats,
    load_defeat_routing_config,
    route_defeat,
)
from arena.reports.issue_payload import (
    build_issue_payload,
    build_issue_payloads_for_report,
    compute_fingerprint,
)
from arena.reports.models import ExecutionMetadata, MatchReport, TrialReport
from arena.reports.scoring import MatchOutcome, MatchScore
from arena.runner.llm_mode import LLMMode

REPO_ROOT = Path(__file__).resolve().parent.parent
SAMPLES_ROOT = REPO_ROOT / "docs" / "samples"

_MATCH_ID = "20260710T000000Z-test-scenario-deadbeef"
_MATCH_STARTED_AT = datetime(2026, 7, 10, 0, 0, 0, tzinfo=UTC)

#: Default `MatchReport.execution` for hand-built fixtures in this module —
#: see `test_reports_defeat.py`'s own `_MOCK_EXECUTION` for why.
_MOCK_EXECUTION = ExecutionMetadata(
    llm_mode=LLMMode.MOCK, deterministic=True, external_model_calls=0, estimated_cost_usd=0.0
)


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
    *,
    trial_id: str,
    tool: str,
    effect: Decision,
    policy_id: str | None = "sample-policy",
    resource: str = "some/resource",
) -> ArenaAuditEvent:
    attempt = _attempt(trial_id=trial_id, tool=tool, resource=resource)
    decision = DefenseDecision(
        effect=effect,
        layer="policy",
        reason="canned test decision",
        policy_id=policy_id,
        severity=Severity.LOW,
    )
    return ArenaAuditEvent.for_decision(match_id=_MATCH_ID, attempt=attempt, decision=decision)


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
        description="A trial used for issue payload tests.",
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
        scenario_description="Scenario used for issue payload tests.",
        timestamp=_MATCH_STARTED_AT,
        agents=tuple(sorted({trial.agent_id for trial in trials})),
        victory_conditions=VictoryConditions(),
        score=score or _zero_score(),
        trials=trials,
        unattributed_audit_events=unattributed_audit_events,
        execution=_MOCK_EXECUTION,
    )


# --- AC1: winning sample produces zero issue payloads -------------------------


def test_build_issue_payloads_for_report_winning_sample_is_empty() -> None:
    report = _load_sample_report("winning-match")

    assert build_issue_payloads_for_report(report) == []


# --- AC2: losing sample's critical escape produces a correctly formatted payload


def test_build_issue_payloads_for_report_losing_sample_critical_escape() -> None:
    report = _load_sample_report("losing-match")

    payloads = build_issue_payloads_for_report(report)

    critical_escape_payloads = [
        payload
        for payload in payloads
        if payload.title.startswith("[Arena Defeat] Critical escape:")
    ]
    assert len(critical_escape_payloads) == 1
    payload = critical_escape_payloads[0]

    assert payload.title == (
        "[Arena Defeat] Critical escape: github-maintainer-dungeon/prompt-injection-code-write"
    )
    assert payload.repo == "ai-agent-assembly/agent-assembly"
    assert payload.labels == ("arena-defeat", "security", "critical-escape")
    assert len(payload.fingerprint) == 64  # sha256 hexdigest

    for expected_field in (
        "**Category:** critical_escape",
        "**Scenario ID:** github-maintainer-dungeon",
        f"**Match ID:** {report.match_id}",
        "**Agent ID:** raw-python-issue-triager",
        "**Framework:** raw-python",
        "**Trial ID:** prompt-injection-code-write",
        "**Expected decision(s):**",
        "**Actual decision(s):**",
        "**Impact / severity:** critical",
        "**Detail:**",
        f"**Full report:** reports/matches/{report.match_id}/arena-report.md",
        f"**Audit log:** reports/matches/{report.match_id}/audit.jsonl",
        "**Suggested labels:** arena-defeat, security, critical-escape",
    ):
        assert expected_field in payload.body, (
            f"missing {expected_field!r} in body:\n{payload.body}"
        )

    # Expected/actual decisions reflect the trial's real divergence: the
    # trial expected `github.contents.write=deny` but the sample's fixture
    # (see tests/report_fixtures.py's `_LOSING_TRIAL_ID`/`_LOSING_TOOL`)
    # rendered it as `allow`.
    assert "github.contents.write=deny" in payload.body
    assert "github.contents.write=allow" in payload.body


# --- AC3: routing reused verbatim from AAASM-4401 (governance vs. arena repo) -


def test_build_issue_payloads_for_report_routes_by_category() -> None:
    trial = _trial_report(
        trial_id="silent-agent-trial",
        expected={"github.issues.comment": Decision.ALLOW},
        passed=False,
        audit_events=(),
    )
    report = _report(trials=(trial,))

    payloads = build_issue_payloads_for_report(report)

    assert len(payloads) == 1
    assert payloads[0].repo == "ai-agent-assembly/arena"
    assert payloads[0].labels == ("scenario-bug",)


def test_build_issue_payload_governance_failure_routes_to_agent_assembly() -> None:
    routing_config = load_defeat_routing_config()
    classification = DefeatClassification(
        category=DefeatCategory.UNEXPECTED_ALLOW,
        detail="Synthetic unexpected allow.",
        trial_id="some-trial",
    )
    report = _report(trials=(_trial_report(trial_id="some-trial", passed=False),))

    payload = build_issue_payload(
        classification, route_defeat(classification, routing_config), report
    )

    assert payload.repo == "ai-agent-assembly/agent-assembly"


# --- Missing-audit / unattributed classification (no trial to look up) --------


def test_build_issue_payload_unattributed_missing_audit() -> None:
    parse_error_event = ArenaAuditEvent.for_parse_error(
        match_id=_MATCH_ID, severity=Severity.LOW, error="malformed marker line"
    )
    report = _report(trials=(), unattributed_audit_events=(parse_error_event,))

    classifications = classify_defeats(report)
    assert len(classifications) == 1

    routing_config = load_defeat_routing_config()
    payload = build_issue_payload(
        classifications[0], route_defeat(classifications[0], routing_config), report
    )

    assert payload.title == "[Arena Defeat] Missing audit: test-scenario/unattributed"
    assert "**Trial ID:** unattributed (no specific trial)" in payload.body
    assert "**Agent ID:** N/A" in payload.body
    assert "**Framework:** N/A" in payload.body
    assert "**Expected decision(s):** N/A (no attributable trial)" in payload.body
    assert "**Actual decision(s):** N/A (no attributable trial)" in payload.body


# --- AC5: fingerprint is stable, and sensitive to the fields it documents -----


def test_compute_fingerprint_is_deterministic() -> None:
    report = _load_sample_report("losing-match")
    classification = classify_defeats(report)[0]

    assert compute_fingerprint(classification, report) == compute_fingerprint(
        classification, report
    )


def test_compute_fingerprint_differs_across_distinct_classifications() -> None:
    # The losing sample's `prompt-injection-code-write` trial produces two
    # classifications (`unexpected_allow` and `critical_escape`, see
    # `test_reports_defeat.py`'s AC2 tests) sharing the same `trial_id` --
    # their fingerprints must still differ, since `category`/`detail` differ.
    report = _load_sample_report("losing-match")
    classifications = classify_defeats(report)

    fingerprints = {compute_fingerprint(c, report) for c in classifications}

    assert len(fingerprints) == len(classifications)


def test_compute_fingerprint_is_stable_across_match_ids() -> None:
    """Two different match runs of the same scenario that hit the same
    trial/category/policy combination must collapse to the same
    fingerprint -- that's the entire point of a duplicate-detection signal
    (see the module docstring's "not part of the fingerprint" note on
    `match_id`).
    """
    trial = _trial_report(
        trial_id="release-trial",
        expected={"github.releases.publish": Decision.DENY},
        passed=False,
        audit_events=(
            _decided_event(
                trial_id="release-trial",
                tool="github.releases.publish",
                effect=Decision.ALLOW,
                policy_id="policy-a",
            ),
        ),
    )
    report_one = MatchReport(
        match_id="match-one",
        scenario_id="test-scenario",
        scenario_name="Test Scenario",
        scenario_description="Scenario used for issue payload tests.",
        timestamp=_MATCH_STARTED_AT,
        agents=("test-agent",),
        victory_conditions=VictoryConditions(),
        score=_zero_score(),
        trials=(trial,),
        execution=_MOCK_EXECUTION,
    )
    report_two = report_one.model_copy(update={"match_id": "match-two"})

    classification_one = classify_defeats(report_one)[0]
    classification_two = classify_defeats(report_two)[0]

    assert compute_fingerprint(classification_one, report_one) == compute_fingerprint(
        classification_two, report_two
    )


def test_compute_fingerprint_differs_by_policy_id() -> None:
    def _report_with_policy(policy_id: str) -> MatchReport:
        trial = _trial_report(
            trial_id="release-trial",
            expected={"github.releases.publish": Decision.DENY},
            passed=False,
            audit_events=(
                _decided_event(
                    trial_id="release-trial",
                    tool="github.releases.publish",
                    effect=Decision.ALLOW,
                    policy_id=policy_id,
                ),
            ),
        )
        return _report(trials=(trial,))

    report_a = _report_with_policy("policy-a")
    report_b = _report_with_policy("policy-b")

    classification_a = classify_defeats(report_a)[0]
    classification_b = classify_defeats(report_b)[0]

    assert compute_fingerprint(classification_a, report_a) != compute_fingerprint(
        classification_b, report_b
    )
