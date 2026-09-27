"""Unit tests for `scripts/render_latest_reports_page.py` (AAASM-4506).

`scripts/` isn't part of the installed `arena` package, so the module is
loaded directly from its file path via `importlib` rather than a normal
`import` statement.

Covers:

- The AAASM-4506 bug: a `reports/latest.json` whose inlined `MatchReport`
  predates AAASM-4406's `schema_version` bump ("1" -> "2", which added the
  required `execution` field) must not raise a `pydantic.ValidationError` —
  `_load_latest` must return `None`, and `main()` must fall back to the same
  placeholder page used when no match has ever run.
- The equivalent case for `reports/leaderboard.json`.
- No regression to the pre-existing "no live matches yet" empty-state
  handling (AAASM-4429): a missing/empty `leaderboard.json` still renders
  the placeholder, and a real, current-schema leaderboard+latest pair still
  renders the full page.
"""

from __future__ import annotations

import importlib.util
import json
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import ModuleType

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
SCRIPT_PATH = REPO_ROOT / "scripts" / "render_latest_reports_page.py"


def _load_script_module() -> ModuleType:
    spec = importlib.util.spec_from_file_location("render_latest_reports_page", SCRIPT_PATH)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


render = _load_script_module()


# --- fixtures ----------------------------------------------------------------------

#: A `latest.json`-shaped payload whose inlined `report` predates AAASM-4406:
#: `report.schema_version == "1"` and no `execution` key at all. The
#: wrapper's own `schema_version` is unchanged ("1", still equal to
#: `LATEST_INDEX_SCHEMA_VERSION`) — exactly mirroring the real stale
#: `reports/latest.json` this bug was filed against, where the wrapper
#: schema hadn't moved but the nested `MatchReport` schema had.
_STALE_LATEST_PAYLOAD = {
    "schema_version": "1",
    "match_id": "stale-match",
    "path": "matches/stale-match/arena-report.json",
    "generated_at": "2026-07-12T09:22:24Z",
    "report": {
        "schema_version": "1",
        "match_id": "stale-match",
        "scenario_id": "github-maintainer-dungeon",
        "scenario_name": "GitHub Maintainer Dungeon",
        "scenario_description": "A scenario used only for this fixture.",
        "timestamp": "2026-07-12T09:22:24Z",
        "agents": ["some-agent"],
        "victory_conditions": {},
        "score": {
            "match_id": "stale-match",
            "critical_escapes": 0,
            "unexpected_allows": 0,
            "secret_exposures": 0,
            "approval_bypasses": 0,
            "missing_audits": 0,
            "agent_runtime_failures": 0,
            "outcome": "agent-assembly wins",
        },
        "trials": [],
        "unattributed_audit_events": [],
        # No "execution" key -- this is the AAASM-4406 required field whose
        # absence is what actually crashes `LatestReportIndex` validation.
    },
}

_STALE_LEADERBOARD_PAYLOAD = {
    "schema_version": "0",
    "generated_at": "2026-07-12T09:22:25Z",
    "matches": [],
}

_CURRENT_LEADERBOARD_PAYLOAD = {
    "schema_version": render.LEADERBOARD_SCHEMA_VERSION,
    "generated_at": "2026-07-12T09:22:25Z",
    "matches": [
        {
            "match_id": "current-match",
            "scenario_id": "github-maintainer-dungeon",
            "outcome": "agent-assembly wins",
            "critical_escapes": 0,
            "generated_at": "2026-07-12T09:22:24Z",
        }
    ],
}

#: The current-schema counterpart of `_STALE_LATEST_PAYLOAD`: same shape, but
#: the nested `MatchReport` carries today's schema version and the
#: AAASM-4406 `execution` block, so `_load_latest` accepts it and the page
#: renders its most-recent-match section rather than falling back.
_CURRENT_LATEST_PAYLOAD = {
    **_STALE_LATEST_PAYLOAD,
    "match_id": "current-match",
    "path": "matches/current-match/arena-report.json",
    "report": {
        **_STALE_LATEST_PAYLOAD["report"],
        "schema_version": render.MATCH_REPORT_SCHEMA_VERSION,
        "match_id": "current-match",
        "execution": {
            "llm_mode": "mock",
            "deterministic": True,
            "external_model_calls": 0,
            "estimated_cost_usd": 0.0,
        },
        "score": {**_STALE_LATEST_PAYLOAD["report"]["score"], "match_id": "current-match"},
    },
}


# --- _load_latest: schema-version-mismatch fallback ---------------------------------


def test_load_latest_returns_none_for_stale_nested_report_schema(tmp_path: Path) -> None:
    """The exact AAASM-4506 shape: wrapper schema unchanged, nested
    `MatchReport.schema_version` stale. Must return `None`, not raise.
    """
    path = tmp_path / "latest.json"
    path.write_text(json.dumps(_STALE_LATEST_PAYLOAD), encoding="utf-8")

    result = render._load_latest(path)

    assert result is None


def test_load_latest_returns_none_for_stale_wrapper_schema(tmp_path: Path) -> None:
    payload = {**_STALE_LATEST_PAYLOAD, "schema_version": "0"}
    path = tmp_path / "latest.json"
    path.write_text(json.dumps(payload), encoding="utf-8")

    result = render._load_latest(path)

    assert result is None


def test_load_latest_returns_none_when_file_missing(tmp_path: Path) -> None:
    assert render._load_latest(tmp_path / "does-not-exist.json") is None


# --- _load_leaderboard: schema-version-mismatch fallback -----------------------------


def test_load_leaderboard_returns_none_for_stale_schema(tmp_path: Path) -> None:
    path = tmp_path / "leaderboard.json"
    path.write_text(json.dumps(_STALE_LEADERBOARD_PAYLOAD), encoding="utf-8")

    result = render._load_leaderboard(path)

    assert result is None


def test_load_leaderboard_returns_current_schema_payload(tmp_path: Path) -> None:
    path = tmp_path / "leaderboard.json"
    path.write_text(json.dumps(_CURRENT_LEADERBOARD_PAYLOAD), encoding="utf-8")

    result = render._load_leaderboard(path)

    assert result is not None
    assert len(result.matches) == 1
    assert result.matches[0].match_id == "current-match"


# --- main(): end-to-end fallback to the placeholder page -----------------------------


@pytest.fixture
def _patched_paths(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Point the script's module-level path constants at an isolated
    `tmp_path` directory instead of this repo's real `reports/`/`docs/`, so
    `main()` can be exercised without touching real files.
    """
    reports_root = tmp_path / "reports"
    reports_root.mkdir()
    docs_root = tmp_path / "docs"
    docs_root.mkdir()
    output_path = docs_root / "latest-reports.md"

    monkeypatch.setattr(render, "REPORTS_ROOT", reports_root)
    monkeypatch.setattr(render, "LEADERBOARD_PATH", reports_root / "leaderboard.json")
    monkeypatch.setattr(render, "LATEST_PATH", reports_root / "latest.json")
    monkeypatch.setattr(render, "OUTPUT_PATH", output_path)
    return reports_root


def test_main_falls_back_to_placeholder_when_latest_json_schema_is_stale(
    _patched_paths: Path,
) -> None:
    reports_root = _patched_paths
    (reports_root / "leaderboard.json").write_text(
        json.dumps(_CURRENT_LEADERBOARD_PAYLOAD), encoding="utf-8"
    )
    (reports_root / "latest.json").write_text(json.dumps(_STALE_LATEST_PAYLOAD), encoding="utf-8")

    render.main()

    assert render.OUTPUT_PATH.read_text(encoding="utf-8") == render._render_placeholder()


def test_main_falls_back_to_placeholder_when_leaderboard_json_schema_is_stale(
    _patched_paths: Path,
) -> None:
    reports_root = _patched_paths
    (reports_root / "leaderboard.json").write_text(
        json.dumps(_STALE_LEADERBOARD_PAYLOAD), encoding="utf-8"
    )

    render.main()

    assert render.OUTPUT_PATH.read_text(encoding="utf-8") == render._render_placeholder()


# --- main(): no regression to AAASM-4429's original empty-state handling ------------


def test_main_renders_placeholder_when_leaderboard_json_missing(_patched_paths: Path) -> None:
    render.main()

    assert render.OUTPUT_PATH.read_text(encoding="utf-8") == render._render_placeholder()


def test_main_renders_placeholder_when_leaderboard_has_zero_matches(
    _patched_paths: Path,
) -> None:
    reports_root = _patched_paths
    empty_leaderboard = {**_CURRENT_LEADERBOARD_PAYLOAD, "matches": []}
    (reports_root / "leaderboard.json").write_text(json.dumps(empty_leaderboard), encoding="utf-8")

    render.main()

    assert render.OUTPUT_PATH.read_text(encoding="utf-8") == render._render_placeholder()


def test_main_renders_full_page_for_current_schema_data(_patched_paths: Path) -> None:
    reports_root = _patched_paths
    (reports_root / "leaderboard.json").write_text(
        json.dumps(_CURRENT_LEADERBOARD_PAYLOAD), encoding="utf-8"
    )

    render.main(now=datetime(2026, 7, 12, 15, 0, tzinfo=timezone.utc))

    output = render.OUTPUT_PATH.read_text(encoding="utf-8")
    assert output != render._render_placeholder()
    assert "## Leaderboard" in output
    assert "current-match" in output


# --- AAASM-6186: the page must state its own freshness ------------------------------

#: `_CURRENT_LEADERBOARD_PAYLOAD` is stamped `2026-07-12T09:22:25Z`. These two
#: clocks sit either side of `STALE_AFTER` relative to that stamp.
_FRESH_NOW = datetime(2026, 7, 12, 15, 0, tzinfo=timezone.utc)
_STALE_NOW = datetime(2026, 9, 26, 12, 17, tzinfo=timezone.utc)


def _render_current(now: datetime, reports_root: Path) -> str:
    """Render the full page (leaderboard *and* most-recent-match section) from
    current-schema data, with the clock injected so every assertion below is
    deterministic.
    """
    (reports_root / "leaderboard.json").write_text(
        json.dumps(_CURRENT_LEADERBOARD_PAYLOAD), encoding="utf-8"
    )
    (reports_root / "latest.json").write_text(
        json.dumps(_CURRENT_LATEST_PAYLOAD), encoding="utf-8"
    )
    render.main(now=now)
    output = render.OUTPUT_PATH.read_text(encoding="utf-8")
    # A placeholder page carries no freshness statement at all, so it would
    # pass a "no warning" assertion vacuously.
    assert output != render._render_placeholder()
    return output


def test_stale_index_is_not_presented_as_current(_patched_paths: Path) -> None:
    """The AAASM-6186 defect. `scheduled-matches` failed to publish for 76
    consecutive days and the page went on presenting that 76-day-old run
    under a heading reading "Latest match", with nothing to distinguish it
    from an hour-old refresh. A bare timestamp is not a freshness claim.
    """
    output = _render_current(_STALE_NOW, _patched_paths)

    assert "## Latest match" not in output
    assert "## Most recent published match" in output
    assert "!!! warning" in output
    assert "76 days old" in output
    assert "not a current view of Arena" in output
    # The reader is pointed at where the failure actually is.
    assert render.WORKFLOW_RUNS_URL in output


def test_fresh_index_carries_an_as_of_line_and_no_warning(_patched_paths: Path) -> None:
    """The freshness statement is unconditional; only the warning is
    conditional. A page that says nothing when fresh would leave a reader
    with no way to tell "fresh" from "the staleness check is broken".
    """
    output = _render_current(_FRESH_NOW, _patched_paths)

    assert "**Published index as of:** 2026-07-12T09:22:25+00:00 (5 hours old)." in output
    assert "!!! warning" not in output
    assert "stale" not in output


def test_the_boundary_is_the_data_timestamp_not_the_build_time(_patched_paths: Path) -> None:
    """Rebuilding the docs must not make old results look fresh: the age is
    computed from the index's own `generated_at`. `documentation.yml`
    regenerates this page on every deploy, so a build-time-derived "fresh"
    stamp would have read as current on all 76 of those days.
    """
    generated_at = datetime.fromisoformat(
        _CURRENT_LEADERBOARD_PAYLOAD["generated_at"].replace("Z", "+00:00")
    )

    just_inside = _render_current(generated_at + render.STALE_AFTER, _patched_paths)
    just_outside = _render_current(
        generated_at + render.STALE_AFTER + timedelta(minutes=1), _patched_paths
    )

    assert "!!! warning" not in just_inside
    assert "!!! warning" in just_outside


@pytest.mark.parametrize(
    ("age", "expected"),
    [
        (timedelta(minutes=30), "under an hour old"),
        (timedelta(hours=1), "1 hour old"),
        (timedelta(hours=5), "5 hours old"),
        (timedelta(days=1), "1 day old"),
        (timedelta(days=76), "76 days old"),
        (timedelta(days=76, hours=13), "76 days old"),
        (timedelta(minutes=-5), "stamped in the future"),
    ],
)
def test_age_is_described_in_units_a_reader_can_act_on(age: timedelta, expected: str) -> None:
    assert render._describe_age(age) == expected


def test_a_future_stamped_index_is_not_reported_as_fresh(_patched_paths: Path) -> None:
    """Clock skew or a hand-edited index must not buy silence. `now` before
    `generated_at` means the age is negative, which is smaller than every
    threshold -- so the staleness branch would pass it, and the as-of line is
    the only thing that can say so.
    """
    output = _render_current(_FRESH_NOW - timedelta(days=365), _patched_paths)

    assert "(stamped in the future)" in output


# --- --require-live-index: the publisher must not ship an unrenderable index --------


def test_require_live_index_refuses_the_stale_nested_report_schema(_patched_paths: Path) -> None:
    """The AAASM-4506 shape again, this time from the publisher's side. Under
    the docs build this silently becomes the placeholder; `scheduled-matches`
    must not publish reports whose page says no match has ever run.
    """
    reports_root = _patched_paths
    (reports_root / "leaderboard.json").write_text(
        json.dumps(_CURRENT_LEADERBOARD_PAYLOAD), encoding="utf-8"
    )
    (reports_root / "latest.json").write_text(json.dumps(_STALE_LATEST_PAYLOAD), encoding="utf-8")

    with pytest.raises(render.UnrenderableIndexError, match="not renderable as a live index"):
        render.main(now=_FRESH_NOW, require_live_index=True)

    # Nothing was written: the caller decides what to do, and a half-written
    # placeholder would be the very page this flag exists to prevent.
    assert not render.OUTPUT_PATH.exists()


@pytest.mark.parametrize(
    "leaderboard",
    [
        pytest.param(None, id="leaderboard-missing"),
        pytest.param(_STALE_LEADERBOARD_PAYLOAD, id="leaderboard-schema-stale"),
        pytest.param({**_CURRENT_LEADERBOARD_PAYLOAD, "matches": []}, id="leaderboard-empty"),
    ],
)
def test_require_live_index_refuses_every_placeholder_path(
    _patched_paths: Path, leaderboard: dict[str, object] | None
) -> None:
    if leaderboard is not None:
        (_patched_paths / "leaderboard.json").write_text(json.dumps(leaderboard), encoding="utf-8")

    with pytest.raises(render.UnrenderableIndexError):
        render.main(now=_FRESH_NOW, require_live_index=True)


def test_require_live_index_is_satisfied_by_a_renderable_index(_patched_paths: Path) -> None:
    """The flag must not be a blanket refusal — good data still renders, so a
    green publish step means something.
    """
    output = _render_current(_FRESH_NOW, _patched_paths)  # asserts it is not the placeholder
    render.OUTPUT_PATH.unlink()

    render.main(now=_FRESH_NOW, require_live_index=True)

    assert render.OUTPUT_PATH.read_text(encoding="utf-8") == output


def test_the_placeholder_path_is_still_the_default() -> None:
    """The docs build calls this script with no arguments and must keep
    building on a repo where no match has run yet.
    """
    assert render._parse_args([]).require_live_index is False
    assert render._parse_args(["--require-live-index"]).require_live_index is True
