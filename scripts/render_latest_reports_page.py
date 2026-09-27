#!/usr/bin/env python3
"""Render `docs/latest-reports.md` from the live static report index
(AAASM-4429).

`reports/leaderboard.json`/`reports/latest.json` (`arena.reports.index.
LeaderboardIndex`/`LatestReportIndex`) live at the repo root, refreshed by
the `scheduled-matches` workflow (AAASM-4428), which publishes them onto
`main` as a pull request (AAASM-6186) — see `reports/README.md`. MkDocs only
builds content under `docs/`, so this script turns that live JSON into a
Markdown page MkDocs can render, rather
than the docs site trying to fetch `reports/*.json` client-side (which isn't
reachable from the deployed site — `mike deploy` only publishes what
`mkdocs build` produces from `docs/`, not the repo root).

Not part of the installed `arena` package — a repo-local build step, run
before `mkdocs build`/`mkdocs serve` so the page reflects whatever is
currently on disk under `reports/`:

    uv run python scripts/render_latest_reports_page.py
    uv run mkdocs build --strict

`.github/workflows/documentation.yml` runs it before every build (PR-check
and deploy alike), so the generated page's *content* is always regenerated
fresh from whatever is on disk under `reports/` at build time — no new commit
required per refresh. The output file (`docs/latest-reports.md`) is
nonetheless committed/tracked (not gitignored): the `git-authors` and
`git-revision-date-localized` MkDocs plugins need existing git history for
the path to pass `mkdocs build --strict`, so the tracked file is a snapshot/
starting point, not the source of truth for the page's content.

Handles the case where no match has ever run (`reports/leaderboard.json`
missing, or present with zero matches) by rendering a placeholder instead of
erroring — a fresh checkout or a repo before AAASM-4428's first scheduled
run is a valid, expected state, not a build failure.

Also handles the case where `reports/latest.json`/`reports/leaderboard.json`
(or the `MatchReport` inlined in `latest.json`) are stamped with a
`schema_version` older than what this script's `arena.reports.index`/
`arena.reports.models` currently expect (AAASM-4506) — e.g. a
`scheduled-matches` run committed before a schema bump like AAASM-4406's
addition of the required `MatchReport.execution` field. Rather than letting
`LatestReportIndex`/`LeaderboardIndex` validation raise, the stored
`schema_version` is checked by name *before* any Pydantic validation is
attempted, and a mismatch is treated the same as "no current data
available" — falling back to the same placeholder used when no match has
ever run at all, since a stale-schema file is just as unusable to this
script as a missing one.
"""

from __future__ import annotations

import argparse
import json
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from pydantic import ValidationError

from arena.reports.index import (
    LATEST_INDEX_SCHEMA_VERSION,
    LEADERBOARD_SCHEMA_VERSION,
    LatestReportIndex,
    LeaderboardIndex,
)
from arena.reports.models import SCHEMA_VERSION as MATCH_REPORT_SCHEMA_VERSION
from arena.reports.scoring import MatchOutcome

REPO_ROOT = Path(__file__).resolve().parent.parent
REPORTS_ROOT = REPO_ROOT / "reports"
LEADERBOARD_PATH = REPORTS_ROOT / "leaderboard.json"
LATEST_PATH = REPORTS_ROOT / "latest.json"
OUTPUT_PATH = REPO_ROOT / "docs" / "latest-reports.md"

#: Live match reports live under `reports/matches/<match-id>/` on `main`
#: (tracked in git, per `reports/README.md`) but not under `docs/`, so they
#: aren't part of the MkDocs-built site itself. Link to them on GitHub
#: instead — a plain blob URL against `main`, always reachable regardless of
#: which docs version/channel a reader is looking at.
GITHUB_MATCH_BASE = "https://github.com/ai-agent-assembly/arena/blob/main/reports/matches"

_OUTCOME_EMOJI = {
    MatchOutcome.AGENT_ASSEMBLY_WINS: "✅",
    MatchOutcome.AGENT_ASSEMBLY_LOSES: "❌",
}

#: How old the published index may be before this page says so in its own
#: words (AAASM-6186). `scheduled-matches` runs daily, so anything past two
#: days means at least one run did not publish. The page previously carried
#: only a bare ISO timestamp under a heading that read "Latest match", which
#: a reader reasonably takes as "current": when the publish step failed for
#: 76 consecutive days, the public page went on presenting 76-day-old results
#: as the latest ones, and nothing on it distinguished that from an hour-old
#: refresh. A timestamp is not a freshness claim; this is.
STALE_AFTER = timedelta(days=2)

WORKFLOW_URL = (
    "https://github.com/ai-agent-assembly/arena/blob/main/.github/workflows/scheduled-matches.yml"
)
WORKFLOW_RUNS_URL = (
    "https://github.com/ai-agent-assembly/arena/actions/workflows/scheduled-matches.yml"
)


def _describe_age(age: timedelta) -> str:
    """Human-readable age, coarse on purpose: this page is rebuilt on every
    docs deploy, so minute-level precision would be noise."""
    if age < timedelta(0):
        # A published index stamped in the future is not something to render a
        # soothing "0 hours old" for.
        return "stamped in the future"
    days = age.days
    if days >= 1:
        return f"{days} day{'s' if days != 1 else ''} old"
    hours = age.seconds // 3600
    if hours >= 1:
        return f"{hours} hour{'s' if hours != 1 else ''} old"
    return "under an hour old"


def _render_freshness(generated_at: datetime, now: datetime) -> list[str]:
    """The explicit as-of statement, plus a warning when the index is stale.

    Rendered from the data's own `generated_at` rather than from the build
    time, so a docs rebuild cannot make old results look fresh.
    """
    age = now - generated_at
    lines = [
        f"**Published index as of:** {generated_at.isoformat()} ({_describe_age(age)}).  ",
        f"Refreshed daily by the [`scheduled-matches`]({WORKFLOW_URL}) workflow.",
        "",
    ]
    if age <= STALE_AFTER:
        return lines
    lines.extend(
        [
            '!!! warning "These results are stale — treat them as a historical snapshot"',
            "",
            f"    The newest published match is {_describe_age(age)}, but matches are meant",
            "    to run every day, so the publish path has not landed a refresh since",
            f"    {generated_at.isoformat()}. **This is not a current view of Arena** —",
            "    more recent matches may have run without their results ever reaching this",
            "    page.",
            "",
            f"    Check the [`scheduled-matches` run history]({WORKFLOW_RUNS_URL}) and any",
            "    open report-refresh pull request.",
            "",
        ]
    )
    return lines


def _match_url(match_id: str, filename: str) -> str:
    return f"{GITHUB_MATCH_BASE}/{match_id}/{filename}"


def _render_placeholder() -> str:
    return """# Latest reports

No live matches have run yet.

The [`scheduled-matches`](https://github.com/ai-agent-assembly/arena/blob/main/.github/workflows/scheduled-matches.yml)
workflow (AAASM-4428) runs real matches on a schedule and publishes the
refreshed `reports/leaderboard.json`/`reports/latest.json` onto `main` as a
pull request — once at least one match has run and that pull request is
merged, this page will show the leaderboard and the most recent match's
result.

In the meantime, see the [report schema](report-schema.md) page for the
static, deterministic sample reports.
"""


def _render_leaderboard(leaderboard: LeaderboardIndex) -> list[str]:
    lines = [
        "## Leaderboard",
        "",
        f"Generated {leaderboard.generated_at.isoformat()} — "
        f"{len(leaderboard.matches)} match(es), most recent first.",
        "",
        "| Match ID | Scenario | Outcome | Critical escapes | Timestamp |",
        "|---|---|---|---:|---|",
    ]
    for entry in leaderboard.matches:
        match_link = f"[`{entry.match_id}`]({_match_url(entry.match_id, 'arena-report.md')})"
        emoji = _OUTCOME_EMOJI[entry.outcome]
        lines.append(
            f"| {match_link} | {entry.scenario_id} | {emoji} {entry.outcome.value} "
            f"| {entry.critical_escapes} | {entry.generated_at.isoformat()} |"
        )
    return lines


def _render_latest(latest: LatestReportIndex) -> list[str]:
    report = latest.report
    emoji = _OUTCOME_EMOJI[report.score.outcome]
    return [
        # "Latest match" claimed currency this page cannot guarantee — all it
        # knows is what was last published (AAASM-6186).
        "## Most recent published match",
        "",
        f"**Match:** [`{report.match_id}`]({_match_url(report.match_id, 'arena-report.md')})  ",
        f"**Scenario:** {report.scenario_name} (`{report.scenario_id}`)  ",
        f"**Result:** {emoji} {report.score.outcome.value}  ",
        f"**Timestamp:** {report.timestamp.isoformat()}  ",
        f"**Agents:** {', '.join(report.agents)}  ",
        f"**Critical escapes:** {report.score.critical_escapes} "
        f"(threshold {report.victory_conditions.critical_escapes})",
        "",
        "Full detail: "
        f"[`arena-report.md`]({_match_url(report.match_id, 'arena-report.md')}) · "
        f"[`arena-report.json`]({_match_url(report.match_id, 'arena-report.json')})",
    ]


def _schema_version_ok(data: dict[str, Any], expected: str) -> bool:
    """`True` if `data`'s own top-level `schema_version` field equals
    `expected`, checked directly against the parsed JSON *before* any
    Pydantic validation is attempted.

    This is the primary detection mechanism for a stale/mismatched schema —
    not `pydantic.ValidationError` — because a future schema bump could
    change *which* fields are required (or their shapes) in ways that don't
    reliably produce the same error shape every time. Checking the version
    string by name catches any such mismatch uniformly, regardless of what
    the resulting validation error would have looked like.
    """
    return data.get("schema_version") == expected


def _load_leaderboard(path: Path) -> LeaderboardIndex | None:
    """Load `leaderboard.json`, returning `None` (rather than raising) if
    the file is missing, its `schema_version` doesn't match
    `LEADERBOARD_SCHEMA_VERSION`, or it otherwise fails to validate.

    Callers treat `None` the same as "no leaderboard data available" — see
    `main`'s placeholder fallback.
    """
    if not path.is_file():
        return None
    data = json.loads(path.read_text(encoding="utf-8"))
    if not _schema_version_ok(data, LEADERBOARD_SCHEMA_VERSION):
        return None
    try:
        return LeaderboardIndex.model_validate(data)
    except ValidationError:
        return None


def _load_latest(path: Path) -> LatestReportIndex | None:
    """Load `latest.json`, returning `None` (rather than raising) if the
    file is missing, its own `schema_version` doesn't match
    `LATEST_INDEX_SCHEMA_VERSION`, the `MatchReport` inlined at `report`
    doesn't match `arena.reports.models.SCHEMA_VERSION`, or it otherwise
    fails to validate.

    The inlined `report.schema_version` check is what actually matters for
    AAASM-4506: `latest.json`'s own wrapper schema (`LATEST_INDEX_SCHEMA_
    VERSION`) hasn't changed, but AAASM-4406 bumped `MatchReport.
    schema_version` "1" -> "2" by adding a required `execution` field — a
    schema-"1" `report` payload has no `execution` key and fails
    `LatestReportIndex` validation.
    """
    if not path.is_file():
        return None
    data = json.loads(path.read_text(encoding="utf-8"))
    if not _schema_version_ok(data, LATEST_INDEX_SCHEMA_VERSION):
        return None
    report_data = data.get("report")
    if not isinstance(report_data, dict) or not _schema_version_ok(
        report_data, MATCH_REPORT_SCHEMA_VERSION
    ):
        return None
    try:
        return LatestReportIndex.model_validate(data)
    except ValidationError:
        return None


def _render_page(
    leaderboard: LeaderboardIndex,
    latest: LatestReportIndex | None,
    now: datetime,
) -> str:
    lines = ["# Latest reports", ""]
    lines.extend(_render_freshness(leaderboard.generated_at, now))
    if latest is not None:
        lines.extend(_render_latest(latest))
        lines.append("")
    lines.extend(_render_leaderboard(leaderboard))
    lines.append("")
    return "\n".join(lines)


class UnrenderableIndexError(RuntimeError):
    """Raised by `main(require_live_index=True)` instead of writing the
    placeholder page — see that parameter's docstring."""


def main(now: datetime | None = None, require_live_index: bool = False) -> None:
    """Render `OUTPUT_PATH` from whatever is currently under `REPORTS_ROOT`.

    `require_live_index=True` turns every placeholder fallback into an
    `UnrenderableIndexError` instead. The docs build wants the fallback (a
    repo with no matches yet must still build), but `scheduled-matches` —
    which is what *produces* the index — wants the opposite: if the reports
    it just wrote don't render, publishing them would land a page saying "no
    live matches have run yet" and the reason would only surface on the
    deploy after the merge (AAASM-6186). A `GITHUB_TOKEN`-opened pull request
    gets no `pull_request` checks at all, so that workflow has to make this
    assertion itself, before it publishes.
    """
    now = now or datetime.now(timezone.utc)

    def render_placeholder(reason: str) -> None:
        if require_live_index:
            raise UnrenderableIndexError(
                f"{reason} — {OUTPUT_PATH} would fall back to the "
                '"no live matches have run yet" placeholder, so the reports under '
                f"{REPORTS_ROOT} are not renderable as a live index."
            )
        OUTPUT_PATH.write_text(_render_placeholder(), encoding="utf-8")
        print(f"wrote {OUTPUT_PATH} (placeholder — {reason})")

    if not LEADERBOARD_PATH.is_file():
        render_placeholder(f"no {LEADERBOARD_PATH} found")
        return

    leaderboard = _load_leaderboard(LEADERBOARD_PATH)
    if leaderboard is None:
        render_placeholder(f"{LEADERBOARD_PATH} schema mismatch or invalid")
        return
    if not leaderboard.matches:
        render_placeholder(f"{LEADERBOARD_PATH} has zero matches")
        return

    latest: LatestReportIndex | None = None
    if LATEST_PATH.is_file():
        latest = _load_latest(LATEST_PATH)
        if latest is None:
            render_placeholder(f"{LATEST_PATH} schema mismatch or invalid")
            return

    OUTPUT_PATH.write_text(_render_page(leaderboard, latest, now), encoding="utf-8")
    age = now - leaderboard.generated_at
    stale = " STALE —" if age > STALE_AFTER else ""
    print(
        f"wrote {OUTPUT_PATH} ({len(leaderboard.matches)} match(es);{stale} {_describe_age(age)})"
    )


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "--require-live-index",
        action="store_true",
        help=(
            "fail instead of writing the placeholder page. For the publisher "
            "(scheduled-matches), which must not ship reports it cannot render."
        ),
    )
    return parser.parse_args(argv)


if __name__ == "__main__":
    args = _parse_args()
    try:
        main(require_live_index=args.require_live_index)
    except UnrenderableIndexError as error:
        raise SystemExit(f"error: {error}") from error
