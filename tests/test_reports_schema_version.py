"""`arena-report.json` schema/version validation (AAASM-4391).

Two things "protect the format from drift" for the JSON output specifically,
distinct from `test_reports_snapshots.py`'s full-content snapshot
comparison:

1. `SCHEMA_VERSION` itself only changes deliberately — a bump is a visible,
   reviewed schema change (see `arena.reports.models`'s own module
   docstring), not an accidental byproduct of an unrelated field edit. This
   module pins the *literal* currently-expected value rather than only
   comparing `MatchReport.schema_version` against the `SCHEMA_VERSION`
   constant it was built from — a careless edit to `SCHEMA_VERSION` itself
   would make that self-referential comparison trivially still pass, so it
   would not actually catch the bump; comparing against a hardcoded literal
   here does.
2. Every persisted `arena-report.json` — the checked-in samples under
   `docs/samples/` included — must validate as a real `MatchReport`
   (`MatchReport.model_validate_json`), not merely "be valid JSON." A
   payload that's valid JSON but has drifted out of the Pydantic schema
   (missing a required field, wrong type, `extra="forbid"` violation) fails
   here even though `json.loads` alone would accept it.
"""

from __future__ import annotations

from pathlib import Path

from arena.reports.models import SCHEMA_VERSION, MatchReport

REPO_ROOT = Path(__file__).resolve().parent.parent
SAMPLES_ROOT = REPO_ROOT / "docs" / "samples"

#: The literal schema version this test suite currently expects.
#: Bumping `arena.reports.models.SCHEMA_VERSION` requires deliberately
#: updating this literal too (and regenerating `docs/samples/` via
#: `scripts/generate_report_samples.py`) — that's the point: a bump is a
#: visible, two-place, reviewed change, not something that can silently
#: slip through because this test compared the constant against itself.
_EXPECTED_SCHEMA_VERSION = "2"


def test_schema_version_constant_matches_expected_literal() -> None:
    assert SCHEMA_VERSION == _EXPECTED_SCHEMA_VERSION


def test_match_report_default_schema_version_matches_expected_literal() -> None:
    """A `MatchReport` built without an explicit `schema_version` gets the
    current default — proving `SCHEMA_VERSION` is actually wired to the
    model's default, not just a same-named, disconnected constant.
    """
    report = MatchReport.model_validate(
        {
            "match_id": "test-match",
            "scenario_id": "test-scenario",
            "scenario_name": "Test Scenario",
            "scenario_description": "A scenario used only to check the schema_version default.",
            "timestamp": "2026-07-10T12:00:00Z",
            "agents": [],
            "victory_conditions": {},
            "score": {
                "match_id": "test-match",
                "critical_escapes": 0,
                "unexpected_allows": 0,
                "secret_exposures": 0,
                "approval_bypasses": 0,
                "missing_audits": 0,
                "agent_runtime_failures": 0,
                "outcome": "agent-assembly wins",
            },
            "trials": [],
            "execution": {
                "llm_mode": "mock",
                "deterministic": True,
                "external_model_calls": 0,
                "estimated_cost_usd": 0.0,
            },
        }
    )

    assert report.schema_version == _EXPECTED_SCHEMA_VERSION


def test_sample_json_reports_declare_expected_schema_version_and_validate() -> None:
    for sample_dir_name in ("winning-match", "losing-match"):
        raw = (SAMPLES_ROOT / sample_dir_name / "arena-report.json").read_text(encoding="utf-8")

        report = MatchReport.model_validate_json(raw)

        assert report.schema_version == _EXPECTED_SCHEMA_VERSION
