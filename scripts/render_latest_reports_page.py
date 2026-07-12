#!/usr/bin/env python3
"""Render `docs/latest-reports.md` from the live static report index
(AAASM-4429).

`reports/leaderboard.json`/`reports/latest.json` (`arena.reports.index.
LeaderboardIndex`/`LatestReportIndex`) live at the repo root, refreshed and
committed to `main` by the `scheduled-matches` workflow (AAASM-4428) — see
`reports/README.md`. MkDocs only builds content under `docs/`, so this
script turns that live JSON into a Markdown page MkDocs can render, rather
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
"""

from __future__ import annotations

from pathlib import Path

from arena.reports.index import LatestReportIndex, LeaderboardIndex
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


def _match_url(match_id: str, filename: str) -> str:
    return f"{GITHUB_MATCH_BASE}/{match_id}/{filename}"


def _render_placeholder() -> str:
    return """# Latest reports

No live matches have run yet.

The [`scheduled-matches`](https://github.com/ai-agent-assembly/arena/blob/main/.github/workflows/scheduled-matches.yml)
workflow (AAASM-4428) runs real matches on a schedule and commits the
refreshed `reports/leaderboard.json`/`reports/latest.json` back to `main` —
once at least one match has run, this page will show the leaderboard and the
most recent match's result.

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
        "## Latest match",
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


def _render_page(leaderboard: LeaderboardIndex, latest: LatestReportIndex | None) -> str:
    lines = ["# Latest reports", ""]
    if latest is not None:
        lines.extend(_render_latest(latest))
        lines.append("")
    lines.extend(_render_leaderboard(leaderboard))
    lines.append("")
    return "\n".join(lines)


def main() -> None:
    if not LEADERBOARD_PATH.is_file():
        OUTPUT_PATH.write_text(_render_placeholder(), encoding="utf-8")
        print(f"wrote {OUTPUT_PATH} (placeholder — no {LEADERBOARD_PATH} found)")
        return

    leaderboard = LeaderboardIndex.model_validate_json(LEADERBOARD_PATH.read_text(encoding="utf-8"))
    if not leaderboard.matches:
        OUTPUT_PATH.write_text(_render_placeholder(), encoding="utf-8")
        print(f"wrote {OUTPUT_PATH} (placeholder — {LEADERBOARD_PATH} has zero matches)")
        return

    latest = (
        LatestReportIndex.model_validate_json(LATEST_PATH.read_text(encoding="utf-8"))
        if LATEST_PATH.is_file()
        else None
    )
    OUTPUT_PATH.write_text(_render_page(leaderboard, latest), encoding="utf-8")
    print(f"wrote {OUTPUT_PATH} ({len(leaderboard.matches)} match(es))")


if __name__ == "__main__":
    main()
