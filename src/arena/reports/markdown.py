"""Render a `MatchReport` (AAASM-4390) as `arena-report.md`: plain
GitHub-flavored Markdown meant to render sensibly both on GitHub and on the
docs site, per AAASM-4388's "human-readable GitHub/docs display" goal.

This module only turns an already-built `MatchReport` into a Markdown
string — it does not read `MatchResult`/`ArenaAuditEvent` itself (that's
`arena.reports.generate.build_report`'s job) and does not write anything to
disk (`arena.reports.generate.generate_report` does). Keeping it a pure
`MatchReport -> str` function makes it trivial to unit test on a hand-built
`MatchReport` without a full match run.

**Redaction.** Every value rendered here — attempt `args` included — comes
straight from `MatchReport.trials[*].audit_events`, which are the same
`ArenaAuditEvent` instances persisted to (and read back from) the match's
audit JSONL. Redaction happens once, at JSONL-persist time
(`arena.integrations.audit._persisted_payload`), so by the time an event
reaches this renderer a `Decision.REDACT`'d attempt's `args` values are
already `arena.integrations.audit.REDACTION_MARKER` — this module has
nothing extra to do to keep a secret out of the rendered Markdown. See
`tests/test_reports_redaction.py` for the explicit proof.
"""

from __future__ import annotations

import json

from arena.reports.models import MatchReport, TrialReport


def _escape(value: str) -> str:
    """Escape `|` and newlines so `value` can't break a Markdown table row."""
    return value.replace("|", "\\|").replace("\n", " ")


def _render_execution(report: MatchReport) -> list[str]:
    execution = report.execution
    determinism_note = (
        "deterministic" if execution.deterministic else "⚠️ NON-DETERMINISTIC — real model calls"
    )
    calls = execution.external_model_calls if execution.external_model_calls is not None else "—"
    cost = execution.estimated_cost_usd if execution.estimated_cost_usd is not None else "—"
    return [
        "## Execution",
        "",
        "| LLM mode | Deterministic | External model calls | Estimated cost (USD) |",
        "|---|---|---:|---:|",
        f"| `{execution.llm_mode.value}` | {determinism_note} | {calls} | {cost} |",
        "",
    ]


def _render_summary(report: MatchReport) -> list[str]:
    score = report.score
    thresholds = report.victory_conditions
    verdict_emoji = "✅" if score.victory else "❌"
    return [
        f"**Result:** {verdict_emoji} {score.outcome.value}",
        "",
        "## Summary",
        "",
        "| Metric | Count | Threshold |",
        "|---|---:|---:|",
        f"| Critical escapes | {score.critical_escapes} | {thresholds.critical_escapes} |",
        f"| Unexpected allows | {score.unexpected_allows} | {thresholds.unexpected_allows} |",
        f"| Secret exposures | {score.secret_exposures} | {thresholds.secret_exposures} |",
        f"| Approval bypasses | {score.approval_bypasses} | — |",
        f"| Missing audits | {score.missing_audits} | — |",
        f"| Agent runtime failures | {score.agent_runtime_failures} | — |",
        "",
    ]


def _render_trial(trial: TrialReport) -> list[str]:
    status = "PASS" if trial.passed else "FAIL"
    behavior = trial.behavior_id if trial.behavior_id is not None else "(default)"
    lines = [
        f"### `{trial.trial_id}` — {trial.agent_id} — {status}",
        "",
        trial.description,
        "",
        f"- **Severity:** {trial.severity.value}",
        f"- **Behavior profile:** {behavior}",
        f"- **Exit code:** {trial.exit_code}",
        f"- **Duration:** {trial.duration_seconds:.2f}s",
    ]
    if trial.error is not None:
        lines.append(f"- **Runner error:** {_escape(trial.error)}")
    lines.append("")

    lines.append("**Expected decisions:**")
    lines.append("")
    lines.append("| Tool | Expected |")
    lines.append("|---|---|")
    for tool, decision in trial.expected.items():
        lines.append(f"| `{_escape(tool)}` | {decision.value} |")
    lines.append("")

    lines.append("**Attempts and decisions:**")
    lines.append("")
    if not trial.audit_events:
        lines.append("_No attempts recorded._")
        lines.append("")
    else:
        lines.append("| Tool | Resource | Args | Actual | Status | Reason |")
        lines.append("|---|---|---|---|---|---|")
        for event in trial.audit_events:
            tool = event.attempt.tool if event.attempt is not None else "—"
            resource = event.attempt.resource if event.attempt is not None else "—"
            args = json.dumps(event.attempt.args, sort_keys=True) if event.attempt else "—"
            actual = event.decision.effect.value if event.decision is not None else "—"
            reason = event.decision.reason if event.decision is not None else (event.error or "—")
            lines.append(
                f"| `{_escape(tool)}` | {_escape(resource)} | {_escape(args)} | "
                f"{actual} | {event.status.value} | {_escape(reason)} |"
            )
        lines.append("")

    return lines


def render_markdown(report: MatchReport) -> str:
    """Render `report` as a complete `arena-report.md` document.

    Structure: match/scenario metadata, then the concise summary (the six
    `MatchScore` counts plus the win/lose verdict — matching the CLI's own
    console summary), then one detailed section per trial (agent, expected
    vs. actual decisions, pass/fail, error), then any audit events that
    couldn't be attributed to a specific trial.
    """
    lines: list[str] = [
        f"# Arena Match Report: `{report.match_id}`",
        "",
        f"**Scenario:** {report.scenario_name} (`{report.scenario_id}`)",
        "",
        report.scenario_description,
        "",
        f"**Timestamp:** {report.timestamp.isoformat()}",
        "",
        f"**Agents:** {', '.join(report.agents) if report.agents else '(none)'}",
        "",
    ]
    lines.extend(_render_execution(report))
    lines.extend(_render_summary(report))
    lines.append("## Trials")
    lines.append("")
    if not report.trials:
        lines.append("_No trials were run._")
        lines.append("")
    for trial in report.trials:
        lines.extend(_render_trial(trial))

    if report.unattributed_audit_events:
        lines.append("## Unattributed Audit Events")
        lines.append("")
        lines.append(
            "Events recorded during the match that could not be linked to a "
            "specific trial/agent (e.g. malformed action-attempt marker lines)."
        )
        lines.append("")
        lines.append("| Status | Severity | Error |")
        lines.append("|---|---|---|")
        for event in report.unattributed_audit_events:
            lines.append(
                f"| {event.status.value} | {event.severity.value} | {_escape(event.error or '—')} |"
            )
        lines.append("")

    return "\n".join(lines) + "\n"
