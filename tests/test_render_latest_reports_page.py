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

    render.main()

    output = render.OUTPUT_PATH.read_text(encoding="utf-8")
    assert output != render._render_placeholder()
    assert "## Leaderboard" in output
    assert "current-match" in output
