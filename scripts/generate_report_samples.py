#!/usr/bin/env python3
"""Regenerate the sample report artifacts under `docs/samples/` (AAASM-4391).

Not part of the installed `arena` package — a repo-local dev utility that
writes out the same deterministic `MatchReport` fixtures
`tests/report_fixtures.py` and `tests/test_reports_snapshots.py` build and
assert against, as real `arena-report.md`/`arena-report.json`/`audit.jsonl`
files a human (or `README.md`) can open directly.

Usage (from the repo root)::

    uv run python scripts/generate_report_samples.py

Because the fixtures in `tests/report_fixtures.py` are fully deterministic
(fixed timestamps/match ids, no wall-clock or UUID input — see that module's
docstring), running this script twice in a row produces byte-identical
output. That's the whole point: if `git diff` shows a change here after a
report-schema change (`arena.reports.models`/`arena.reports.generate`/
`arena.reports.markdown`), the diff *is* the drift `tests/test_reports_snapshots.py`
is designed to catch — regenerate, review the diff, and commit both the
source change and the updated samples together.
"""

from __future__ import annotations

import sys
import tempfile
from pathlib import Path

from arena.reports.generate import ARENA_REPORT_JSON_FILENAME, ARENA_REPORT_MD_FILENAME
from arena.reports.markdown import render_markdown
from arena.reports.models import MatchReport
from arena.runner.match import AUDIT_LOG_FILENAME

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "tests"))

import report_fixtures as rf  # noqa: E402  (needs the sys.path.insert above)

SAMPLES_ROOT = REPO_ROOT / "docs" / "samples"


def _write_sample(*, subdir_name: str, report: MatchReport, audit_source: Path) -> None:
    out_dir = SAMPLES_ROOT / subdir_name
    out_dir.mkdir(parents=True, exist_ok=True)

    (out_dir / ARENA_REPORT_JSON_FILENAME).write_text(
        report.model_dump_json(indent=2) + "\n", encoding="utf-8"
    )
    (out_dir / ARENA_REPORT_MD_FILENAME).write_text(render_markdown(report), encoding="utf-8")
    (out_dir / AUDIT_LOG_FILENAME).write_text(
        audit_source.read_text(encoding="utf-8"), encoding="utf-8"
    )
    print(f"wrote {out_dir}")


def main() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        tmp_path = Path(tmp)
        winning_audit = tmp_path / "winning-audit.jsonl"
        losing_audit = tmp_path / "losing-audit.jsonl"

        winning = rf.build_winning_match_report(audit_scratch_path=winning_audit)
        losing = rf.build_losing_match_report(audit_scratch_path=losing_audit)

        _write_sample(subdir_name="winning-match", report=winning, audit_source=winning_audit)
        _write_sample(subdir_name="losing-match", report=losing, audit_source=losing_audit)


if __name__ == "__main__":
    main()
