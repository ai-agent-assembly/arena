"""`refresh_static_index`: derive the static, website/docs-consumable "index"
artifacts (`latest.json`, `latest.md`, `leaderboard.json`) on top of the
durable per-match reports `arena.reports.generate.generate_report` already
writes under `<reports_root>/<match-id>/`.

This is AAASM-4397, the foundational subtask of AAASM-4396's Story: define
the static report artifact layout a website or docs site can consume
directly (by fetching a URL) without running Arena or standing up a backend
service. AAASM-4398/4399 build on top of whatever shape this module ships
with — see `LATEST_INDEX_SCHEMA_VERSION`/`LEADERBOARD_SCHEMA_VERSION` for why
that matters, mirroring `arena.reports.models.SCHEMA_VERSION`'s own note.

## Layout

    <reports_root>/                    # parent of the per-match root, e.g. `reports/`
        latest.json                    # LatestReportIndex — most recent match, full report inlined
        latest.md                      # render_markdown() of that same match's report
        leaderboard.json               # LeaderboardIndex — one summary row per known match
        matches/
            <match-id>/
                arena-report.md
                arena-report.json
                audit.jsonl

This module's own `reports_root` parameter is the *same* value already
passed to `generate_report`/`aasm-arena run --reports-root` (default
`reports/matches` — the per-match directory root), not the top-level
`reports/` directory itself. `latest.json`/`latest.md`/`leaderboard.json`
are written into its **parent** (`reports_root.parent`), since they are
static-site-wide, not per-match, and a per-match root's parent is exactly
"one level up from where matches live" regardless of what a caller names it.

## Why scan the filesystem instead of taking the just-generated report directly

`refresh_static_index` is a standalone function that rebuilds
`latest.json`/`latest.md`/`leaderboard.json` from whatever
`arena-report.json` files already exist under `reports_root`, rather than
accepting the just-built `MatchReport` as a parameter. That makes it
callable on its own (e.g. to repair/rebuild the index without re-running a
match) as well as right after `generate_report()` inside `aasm-arena run`'s
`run_command` — both call sites get identical, correct output because there
is exactly one code path deciding what "latest" and "leaderboard" mean,
driven by what is actually on disk.

"Latest" is whichever `MatchReport.timestamp` (the match's own start time,
not file mtime — mtimes aren't reliably preserved across a git checkout or
CI artifact copy) is greatest across every `reports_root/*/arena-report.json`
found, with `match_id` as a deterministic tie-break for the (practically
never occurring) case of two matches sharing an identical start instant.

## Scope

`leaderboard.json` is deliberately a plain per-match summary built by
scanning today's `reports_root/matches/` on disk each time it's refreshed —
not a persistent match-history database. There is currently no store of
matches beyond what's sitting in `reports_root`, and adding one is out of
this subtask's scope (see AAASM-4396's Story and AAASM-4397's own AC:
"placeholder or summary file").
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path

from pydantic import BaseModel, ConfigDict, Field

from arena.reports.generate import ARENA_REPORT_JSON_FILENAME
from arena.reports.markdown import render_markdown
from arena.reports.models import MatchReport
from arena.reports.scoring import MatchOutcome

#: Filenames written under `reports_root.parent` by `refresh_static_index`.
LATEST_JSON_FILENAME = "latest.json"
LATEST_MD_FILENAME = "latest.md"
LEADERBOARD_JSON_FILENAME = "leaderboard.json"

#: `latest.json`/`leaderboard.json` schema versions, persisted verbatim as
#: each model's own `schema_version` field. Plain strings (not ints), same
#: convention as `arena.reports.models.SCHEMA_VERSION`, so a future bump can
#: move to "1.1"/"2" freely without a type change. Independent of
#: `arena.reports.models.SCHEMA_VERSION` — `latest.json` inlines a full
#: `MatchReport` (itself carrying its own `schema_version`), but the wrapper
#: shape around it (pointer fields) can evolve on its own timeline.
LATEST_INDEX_SCHEMA_VERSION = "1"
LEADERBOARD_SCHEMA_VERSION = "1"


class LatestReportIndex(BaseModel):
    """`latest.json`'s schema: pointer metadata plus the full most-recent
    `MatchReport` inlined, so a static site or docs consumer can fetch this
    one URL and get everything it needs in a single request.

    Fields:
        schema_version: See `LATEST_INDEX_SCHEMA_VERSION`.
        match_id: The most recent match's id — same as `report.match_id`,
            duplicated at this level so a consumer can read it without
            reaching into the nested report.
        path: The most recent match's own `arena-report.json`, relative to
            this file's own directory (`reports_root.parent`) — e.g.
            `"matches/<match-id>/arena-report.json"` — so a consumer that
            wants the per-match Markdown/JSONL siblings too knows where to
            look without guessing the layout.
        generated_at: When this index file was written (i.e. when
            `refresh_static_index` ran), distinct from `report.timestamp`
            (when the match itself started).
        report: The full `MatchReport` for the most recent match, byte-for-
            byte the same shape as that match's own `arena-report.json`.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_version: str = Field(default=LATEST_INDEX_SCHEMA_VERSION, min_length=1)
    match_id: str = Field(min_length=1)
    path: str = Field(min_length=1)
    generated_at: datetime
    report: MatchReport


class LeaderboardEntry(BaseModel):
    """One summary row in `leaderboard.json`.

    Fields:
        match_id/scenario_id: The match's own identifiers.
        outcome: The match's final verdict (`MatchScore.outcome`).
        critical_escapes: `MatchScore.critical_escapes` — the headline
            failure-mode count, surfaced here so a leaderboard reader can
            spot the worst matches without opening each one's full report.
        generated_at: The match's own start time (`MatchReport.timestamp`),
            not this leaderboard file's own generation time (see
            `LeaderboardIndex.generated_at` for that).
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    match_id: str = Field(min_length=1)
    scenario_id: str = Field(min_length=1)
    outcome: MatchOutcome
    critical_escapes: int = Field(ge=0)
    generated_at: datetime


class LeaderboardIndex(BaseModel):
    """`leaderboard.json`'s schema: every known match's summary row, most
    recent first.

    Fields:
        schema_version: See `LEADERBOARD_SCHEMA_VERSION`.
        generated_at: When this file was written (i.e. when
            `refresh_static_index` ran).
        matches: One `LeaderboardEntry` per `arena-report.json` found under
            `reports_root`, ordered most-recent-first. Empty when no match
            reports exist yet — a genuinely empty leaderboard, not an
            error.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_version: str = Field(default=LEADERBOARD_SCHEMA_VERSION, min_length=1)
    generated_at: datetime
    matches: tuple[LeaderboardEntry, ...] = Field(default_factory=tuple)


def _discover_match_reports(reports_root: Path) -> list[MatchReport]:
    """Every `MatchReport` found under `reports_root/*/arena-report.json`.

    Returns an empty list (not an error) when `reports_root` doesn't exist
    yet — a fresh checkout with no matches run is a valid, expected state
    for `refresh_static_index` to handle.
    """
    if not reports_root.is_dir():
        return []
    reports = []
    for report_path in sorted(reports_root.glob(f"*/{ARENA_REPORT_JSON_FILENAME}")):
        payload = json.loads(report_path.read_text(encoding="utf-8"))
        reports.append(MatchReport.model_validate(payload))
    return reports


def refresh_static_index(reports_root: Path, *, now: datetime | None = None) -> None:
    """Rebuild `latest.json`, `latest.md`, and `leaderboard.json` under
    `reports_root.parent` from every `arena-report.json` found under
    `reports_root`.

    `reports_root` is the same per-match directory root already passed to
    `arena.reports.generate.generate_report` (default `reports/matches`) —
    see the module docstring's "Layout" section for exactly where each
    output file lands.

    `leaderboard.json` is always (re)written, including as a genuinely
    empty `{"matches": [], ...}` when no match reports exist yet.
    `latest.json`/`latest.md` are only written when at least one match
    report was found — there is no "latest" to point to otherwise, and
    writing a placeholder would be indistinguishable from a real (if
    minimal) match report to a consumer parsing it as one.

    `now` overrides "when this refresh happened" (`LatestReportIndex.
    generated_at`/`LeaderboardIndex.generated_at`); defaults to the real
    current time. Exposed as a parameter so callers that need deterministic
    output (e.g. tests) don't have to reach for `freezegun` or similar.
    """
    static_root = reports_root.parent
    reports = _discover_match_reports(reports_root)
    generated_at = now if now is not None else datetime.now(UTC)

    static_root.mkdir(parents=True, exist_ok=True)

    ordered = sorted(reports, key=lambda report: (report.timestamp, report.match_id), reverse=True)
    leaderboard = LeaderboardIndex(
        generated_at=generated_at,
        matches=tuple(
            LeaderboardEntry(
                match_id=report.match_id,
                scenario_id=report.scenario_id,
                outcome=report.score.outcome,
                critical_escapes=report.score.critical_escapes,
                generated_at=report.timestamp,
            )
            for report in ordered
        ),
    )
    (static_root / LEADERBOARD_JSON_FILENAME).write_text(
        leaderboard.model_dump_json(indent=2) + "\n", encoding="utf-8"
    )

    if not ordered:
        return

    latest_report = ordered[0]
    latest_index = LatestReportIndex(
        match_id=latest_report.match_id,
        path=f"matches/{latest_report.match_id}/{ARENA_REPORT_JSON_FILENAME}",
        generated_at=generated_at,
        report=latest_report,
    )
    (static_root / LATEST_JSON_FILENAME).write_text(
        latest_index.model_dump_json(indent=2) + "\n", encoding="utf-8"
    )
    (static_root / LATEST_MD_FILENAME).write_text(render_markdown(latest_report), encoding="utf-8")
