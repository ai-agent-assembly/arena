"""Unit tests for `arena.reports.index.refresh_static_index` (AAASM-4397):
building `latest.json`/`latest.md`/`leaderboard.json` from whatever match
reports already exist under a `reports_root` — the same per-match directory
root `arena.reports.generate.generate_report` writes to.

Matches are written via the real `generate_report` (not hand-crafted JSON
files) so these tests exercise the exact on-disk shape `aasm-arena run`
produces, mirroring `test_reports_generate.py`'s own fixture style.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path

from arena.integrations.audit import ArenaAuditEvent
from arena.integrations.decision import DefenseDecision
from arena.integrations.models import ArenaActionAttempt
from arena.models.scenario import Decision, ScenarioSpec, Severity, TrialSpec, VictoryConditions
from arena.reports.generate import ARENA_REPORT_JSON_FILENAME, generate_report
from arena.reports.index import (
    LATEST_INDEX_SCHEMA_VERSION,
    LATEST_JSON_FILENAME,
    LATEST_MD_FILENAME,
    LEADERBOARD_JSON_FILENAME,
    LEADERBOARD_SCHEMA_VERSION,
    LatestReportIndex,
    LeaderboardIndex,
    refresh_static_index,
)
from arena.reports.markdown import render_markdown
from arena.reports.scoring import MatchOutcome, score_match
from arena.runner.base import AgentRunResult
from arena.runner.events import MatchEvent, MatchEventType
from arena.runner.match import MatchResult, TrialOutcome


def _trial(*, id: str = "some-trial") -> TrialSpec:
    return TrialSpec(
        id=id,
        description="A trial used for static-index tests.",
        expected={"some.action": Decision.ALLOW},
        severity=Severity.LOW,
    )


def _scenario(*, scenario_id: str, trial_ids: list[str]) -> ScenarioSpec:
    return ScenarioSpec(
        id=scenario_id,
        name="Test Scenario",
        description="Scenario used for static-index tests.",
        victory_conditions=VictoryConditions(),
        trials=trial_ids,
    )


def _outcome(*, trial: TrialSpec) -> TrialOutcome:
    return TrialOutcome(
        trial=trial,
        agent_id="agent-a",
        result=AgentRunResult(exit_code=0, stdout="", stderr="", duration_seconds=1.0),
        passed=True,
        error=None,
    )


def _decided_event(*, match_id: str, trial_id: str) -> ArenaAuditEvent:
    attempt = ArenaActionAttempt(
        agent_id="agent-a",
        framework="raw-python",
        scenario_id="test-scenario",
        trial_id=trial_id,
        tool="some.action",
        resource="some/resource",
    )
    decision = DefenseDecision(
        effect=Decision.ALLOW, layer="policy", reason="canned", severity=Severity.LOW
    )
    return ArenaAuditEvent.for_decision(match_id=match_id, attempt=attempt, decision=decision)


def _write_match(
    *, reports_root: Path, match_id: str, scenario_id: str, timestamp: datetime
) -> None:
    """Write one match's report artifacts under `reports_root/<match_id>/`
    via the real `generate_report`, exactly as `aasm-arena run` would.
    """
    trial = _trial()
    scenario = _scenario(scenario_id=scenario_id, trial_ids=[trial.id])
    match_result = MatchResult(
        match_id=match_id,
        scenario=scenario,
        workspace=Path("unused-workspace"),
        events=(
            MatchEvent(
                type=MatchEventType.MATCH_STARTED,
                match_id=match_id,
                timestamp=timestamp,
                scenario_id=scenario_id,
            ),
        ),
        trial_outcomes=(_outcome(trial=trial),),
        critical_escapes=0,
        victory_conditions_violated=False,
    )
    audit_events = [_decided_event(match_id=match_id, trial_id=trial.id)]
    score = score_match(match_result, scenario, audit_events)
    generate_report(match_result, score, audit_events, reports_root=reports_root)


# --- no matches yet ------------------------------------------------------------


def test_refresh_static_index_with_no_matches_writes_empty_leaderboard_only(
    tmp_path: Path,
) -> None:
    reports_root = tmp_path / "reports" / "matches"

    refresh_static_index(reports_root)

    static_root = tmp_path / "reports"
    leaderboard = LeaderboardIndex.model_validate_json(
        (static_root / LEADERBOARD_JSON_FILENAME).read_text(encoding="utf-8")
    )
    assert leaderboard.schema_version == LEADERBOARD_SCHEMA_VERSION
    assert leaderboard.matches == ()
    assert not (static_root / LATEST_JSON_FILENAME).exists()
    assert not (static_root / LATEST_MD_FILENAME).exists()


# --- single match ----------------------------------------------------------------


def test_refresh_static_index_single_match(tmp_path: Path) -> None:
    reports_root = tmp_path / "reports" / "matches"
    fixed_now = datetime(2026, 7, 10, 12, 0, 0, tzinfo=UTC)
    _write_match(
        reports_root=reports_root,
        match_id="match-one",
        scenario_id="scenario-a",
        timestamp=fixed_now,
    )

    refresh_static_index(reports_root, now=fixed_now)

    static_root = tmp_path / "reports"
    latest = LatestReportIndex.model_validate_json(
        (static_root / LATEST_JSON_FILENAME).read_text(encoding="utf-8")
    )
    assert latest.schema_version == LATEST_INDEX_SCHEMA_VERSION
    assert latest.match_id == "match-one"
    assert latest.path == f"matches/match-one/{ARENA_REPORT_JSON_FILENAME}"
    assert latest.generated_at == fixed_now
    assert latest.report.match_id == "match-one"

    on_disk_report_raw = (reports_root / "match-one" / ARENA_REPORT_JSON_FILENAME).read_text(
        encoding="utf-8"
    )
    assert latest.report.model_dump_json(indent=2) + "\n" == on_disk_report_raw

    expected_markdown = render_markdown(latest.report)
    assert (static_root / LATEST_MD_FILENAME).read_text(encoding="utf-8") == expected_markdown

    leaderboard = LeaderboardIndex.model_validate_json(
        (static_root / LEADERBOARD_JSON_FILENAME).read_text(encoding="utf-8")
    )
    assert len(leaderboard.matches) == 1
    entry = leaderboard.matches[0]
    assert entry.match_id == "match-one"
    assert entry.scenario_id == "scenario-a"
    assert entry.outcome is MatchOutcome.AGENT_ASSEMBLY_WINS
    assert entry.critical_escapes == 0
    assert entry.generated_at == fixed_now


# --- multiple matches: ordering + tie-break --------------------------------------


def test_refresh_static_index_picks_most_recent_by_timestamp(tmp_path: Path) -> None:
    reports_root = tmp_path / "reports" / "matches"
    older = datetime(2026, 7, 10, 10, 0, 0, tzinfo=UTC)
    newer = datetime(2026, 7, 10, 11, 0, 0, tzinfo=UTC)
    _write_match(
        reports_root=reports_root,
        match_id="match-older",
        scenario_id="scenario-a",
        timestamp=older,
    )
    _write_match(
        reports_root=reports_root,
        match_id="match-newer",
        scenario_id="scenario-a",
        timestamp=newer,
    )

    refresh_static_index(reports_root)

    static_root = tmp_path / "reports"
    latest = LatestReportIndex.model_validate_json(
        (static_root / LATEST_JSON_FILENAME).read_text(encoding="utf-8")
    )
    assert latest.match_id == "match-newer"

    leaderboard = LeaderboardIndex.model_validate_json(
        (static_root / LEADERBOARD_JSON_FILENAME).read_text(encoding="utf-8")
    )
    assert [entry.match_id for entry in leaderboard.matches] == ["match-newer", "match-older"]


def test_refresh_static_index_tie_breaks_on_match_id_when_timestamps_match(
    tmp_path: Path,
) -> None:
    reports_root = tmp_path / "reports" / "matches"
    same_time = datetime(2026, 7, 10, 10, 0, 0, tzinfo=UTC)
    _write_match(
        reports_root=reports_root, match_id="match-a", scenario_id="scenario-a", timestamp=same_time
    )
    _write_match(
        reports_root=reports_root, match_id="match-b", scenario_id="scenario-a", timestamp=same_time
    )

    refresh_static_index(reports_root)

    static_root = tmp_path / "reports"
    latest = LatestReportIndex.model_validate_json(
        (static_root / LATEST_JSON_FILENAME).read_text(encoding="utf-8")
    )
    # "match-b" > "match-a" lexically -- a deterministic tie-break, not
    # insertion/filesystem-iteration order.
    assert latest.match_id == "match-b"


# --- matches/ directories are never overwritten by static-index files -----------


def test_refresh_static_index_never_touches_per_match_directories(tmp_path: Path) -> None:
    reports_root = tmp_path / "reports" / "matches"
    fixed_now = datetime(2026, 7, 10, 12, 0, 0, tzinfo=UTC)
    _write_match(
        reports_root=reports_root,
        match_id="match-one",
        scenario_id="scenario-a",
        timestamp=fixed_now,
    )
    before = (reports_root / "match-one" / ARENA_REPORT_JSON_FILENAME).read_text(encoding="utf-8")

    refresh_static_index(reports_root)
    refresh_static_index(reports_root)  # idempotent re-run

    after = (reports_root / "match-one" / ARENA_REPORT_JSON_FILENAME).read_text(encoding="utf-8")
    assert before == after
    assert (reports_root / "match-one").is_dir()


# --- schema shape -----------------------------------------------------------------


def test_leaderboard_entry_outcome_serializes_as_plain_string(tmp_path: Path) -> None:
    reports_root = tmp_path / "reports" / "matches"
    fixed_now = datetime(2026, 7, 10, 12, 0, 0, tzinfo=UTC)
    _write_match(
        reports_root=reports_root,
        match_id="match-one",
        scenario_id="scenario-a",
        timestamp=fixed_now,
    )

    refresh_static_index(reports_root)

    static_root = tmp_path / "reports"
    payload = json.loads((static_root / LEADERBOARD_JSON_FILENAME).read_text(encoding="utf-8"))
    assert payload["matches"][0]["outcome"] == "agent-assembly wins"
