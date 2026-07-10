"""Snapshot tests for `arena-report.md`/`arena-report.json` (AAASM-4391).

Compares Markdown/JSON rendered from the deterministic fixtures in
`tests/report_fixtures.py` against the checked-in expected snapshot files
under `docs/samples/<winning-match|losing-match>/` — the same files
`scripts/generate_report_samples.py` writes and `README.md` links to, so
these tests double as "the linked sample files are exactly what the current
code produces," not a separately-maintained copy that can drift from them.

**Determinism strategy.** `tests/report_fixtures.py`'s module docstring
covers this in full; the short version: every fixture input (timestamps,
match ids, attempt/decision content) is fixed at fixture-build time rather
than sourced from wall-clock time or a random UUID, so two independent
builds of the same fixture produce byte-identical `MatchReport` output.
`test_reports_snapshots_are_deterministic_across_independent_builds` below
is the direct proof of that, run on every test invocation rather than only
trusted from the module docstring's claim.

**Failure mode.** A full-string comparison against the checked-in snapshot
file is deliberate, not a partial/structural diff: pytest's default assert
rewriting on a multi-line string equality prints a full unified diff, which
is the clearest possible signal for "here is exactly what drifted" — a
schema field added/removed/renamed, a Markdown section reordered, wording
changed, etc. If a genuine, intended report-format change lands, the fix is
to review that diff, then rerun `scripts/generate_report_samples.py` to
regenerate `docs/samples/` and commit the new snapshots alongside the
source change.
"""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

import pytest

from arena.reports.markdown import render_markdown
from arena.reports.models import MatchReport
from report_fixtures import build_losing_match_report, build_winning_match_report

REPO_ROOT = Path(__file__).resolve().parent.parent
SAMPLES_ROOT = REPO_ROOT / "docs" / "samples"

#: A `build_winning_match_report`/`build_losing_match_report`-shaped fixture
#: builder: takes the audit-log scratch path, returns the assembled report.
ReportBuilder = Callable[..., MatchReport]


@pytest.mark.parametrize(
    "sample_dir_name,builder",
    [
        ("winning-match", build_winning_match_report),
        ("losing-match", build_losing_match_report),
    ],
)
def test_markdown_snapshot_matches_checked_in_sample(
    sample_dir_name: str, builder: ReportBuilder, tmp_path: Path
) -> None:
    report = builder(audit_scratch_path=tmp_path / "audit.jsonl")
    actual_markdown = render_markdown(report)
    expected_markdown = (SAMPLES_ROOT / sample_dir_name / "arena-report.md").read_text(
        encoding="utf-8"
    )

    assert actual_markdown == expected_markdown


@pytest.mark.parametrize(
    "sample_dir_name,builder",
    [
        ("winning-match", build_winning_match_report),
        ("losing-match", build_losing_match_report),
    ],
)
def test_json_snapshot_matches_checked_in_sample(
    sample_dir_name: str, builder: ReportBuilder, tmp_path: Path
) -> None:
    report = builder(audit_scratch_path=tmp_path / "audit.jsonl")
    actual_json = report.model_dump_json(indent=2) + "\n"
    expected_json = (SAMPLES_ROOT / sample_dir_name / "arena-report.json").read_text(
        encoding="utf-8"
    )

    assert actual_json == expected_json


def test_reports_snapshots_are_deterministic_across_independent_builds(tmp_path: Path) -> None:
    """Direct proof of `tests/report_fixtures.py`'s determinism claim: two
    independently-built winning (and losing) reports, from separate audit
    scratch files, serialize identically.
    """
    winning_first = build_winning_match_report(audit_scratch_path=tmp_path / "win-1.jsonl")
    winning_second = build_winning_match_report(audit_scratch_path=tmp_path / "win-2.jsonl")
    assert winning_first.model_dump_json() == winning_second.model_dump_json()
    assert render_markdown(winning_first) == render_markdown(winning_second)

    losing_first = build_losing_match_report(audit_scratch_path=tmp_path / "lose-1.jsonl")
    losing_second = build_losing_match_report(audit_scratch_path=tmp_path / "lose-2.jsonl")
    assert losing_first.model_dump_json() == losing_second.model_dump_json()
    assert render_markdown(losing_first) == render_markdown(losing_second)


def test_losing_sample_has_exactly_one_critical_escape(tmp_path: Path) -> None:
    report = build_losing_match_report(audit_scratch_path=tmp_path / "audit.jsonl")

    assert report.score.critical_escapes == 1
    assert report.score.outcome.value == "agent-assembly loses"


def test_winning_sample_has_zero_failures(tmp_path: Path) -> None:
    report = build_winning_match_report(audit_scratch_path=tmp_path / "audit.jsonl")

    assert report.score.critical_escapes == 0
    assert report.score.unexpected_allows == 0
    assert report.score.secret_exposures == 0
    assert report.score.outcome.value == "agent-assembly wins"


def test_checked_in_json_samples_round_trip_through_match_report(tmp_path: Path) -> None:
    """The checked-in `docs/samples/*/arena-report.json` files are
    themselves valid `MatchReport` payloads, independent of whether they
    still match the freshly-built fixtures above — a belt-and-suspenders
    check against a sample file being hand-edited into an invalid shape.
    """
    for sample_dir_name in ("winning-match", "losing-match"):
        raw = (SAMPLES_ROOT / sample_dir_name / "arena-report.json").read_text(encoding="utf-8")
        MatchReport.model_validate_json(raw)
