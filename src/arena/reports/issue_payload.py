"""Build the GitHub issue title/body PAYLOAD for one routed Arena defeat.

This is AAASM-4402, the follow-up to AAASM-4401's classifier/router
(`arena.reports.defeat`): `classify_defeats` turns a `MatchReport` into
`DefeatClassification`s, `route_defeat` looks each one up in
`defeat_routing.yaml` to get a `DefeatRouting`, and this module turns that
routing decision into an `IssuePayload` — the exact title/body/repo/labels a
human (or a future automation) would hand to `gh issue create` or the GitHub
REST/GraphQL API.

**This module never calls the GitHub API.** Filing the issue for real is a
maintainer-triggered follow-up action, explicitly out of scope for this
subtask (see AAASM-4402's own "Out of Scope" note) — every function here is
a pure, deterministic transformation of already-loaded `MatchReport`/
`DefeatClassification`/`DefeatRouting` data, which is exactly what makes it
testable via `pytest` with no network access or GitHub credentials (AC4).

**Duplicate-issue-prevention fingerprint strategy (AC5).** `compute_fingerprint`
hashes a fixed, ordered set of fields:

1. `report.scenario_id` — which scenario produced this defeat.
2. `classification.trial_id`, or the literal sentinel `"unattributed"` for a
   `MISSING_AUDIT` classification derived from `report.unattributed_audit_events`
   (a parse-error event with no `attempt`, and therefore no trial — see
   `arena.reports.defeat`'s module docstring).
3. `classification.category.value`.
4. `classification.detail` — already the deterministic, human-readable
   encoding of the specific tool/resource/expected/actual values that
   triggered this signal (see `arena.reports.defeat._classify_trial`'s
   per-category detail strings). `DefeatClassification` itself does not
   carry those as separate structured fields, and extracting them back out
   of `detail` via string-parsing would be more fragile than hashing the
   already-stable string `_classify_trial` produces from exactly those
   values in the first place.
5. Every distinct, non-`None` `DefenseDecision.policy_id` recorded across the
   attributed trial's audit events (sorted, comma-joined), best effort. A
   `DefeatClassification` doesn't carry a policy id of its own — routing
   only ever needed the category, not which specific policy rendered a
   decision (AAASM-4401's model is intentionally minimal) — so this looks
   it up from `MatchReport.trials` instead of adding a field to that
   already-merged model. Included so that if a *different* policy starts
   producing the same defeat, that's treated as a distinct fingerprint
   rather than silently deduplicated against the old one.

`match_id` is deliberately **not** part of the fingerprint: two separate
match runs of the same scenario that hit the same trial/category/detail/
policy combination should collapse to the same fingerprint — that's the
entire point of a duplicate-issue-prevention signal. A caller wiring this up
to real issue creation would search open issues for one whose body/a hidden
marker contains this fingerprint before filing a new one; this module only
computes the value, it never performs that search itself.
"""

from __future__ import annotations

import hashlib

from pydantic import BaseModel, ConfigDict, Field

from arena.integrations.audit import AuditEventStatus
from arena.reports.defeat import (
    DefeatClassification,
    DefeatRouting,
    classify_defeats,
    load_defeat_routing_config,
    route_defeat,
)
from arena.reports.models import MatchReport, TrialReport

#: Root under which `arena.reports.generate.generate_report` writes durable
#: report artifacts (`<REPORTS_ROOT>/<match_id>/arena-report.md`, etc.) — see
#: that module's own docstring. A relative repo path, not a URL: exactly how
#: this repo's report artifacts are hosted (a docs site, raw GitHub blob
#: links, ...) isn't settled yet, so a relative path that resolves from this
#: repo's root is the least presumptuous link to put in an issue body.
REPORTS_ROOT = "reports/matches"


class IssuePayload(BaseModel):
    """The exact GitHub issue a maintainer (or a future automation) would
    file for one routed Arena defeat.

    `extra="forbid"` and `frozen=True` mirror the rest of `arena.reports`'
    convention for a value describing something already fully decided.

    Fields:
        title: The issue title — `routing.title_prefix` plus scenario/trial
            context, see `build_issue_payload`.
        body: The issue body in Markdown, carrying every evidence field
            `build_issue_payload`'s own docstring lists.
        repo: `<org>/<repo>` to file the issue against (`routing.repo`).
        labels: Labels the issue should carry (`routing.labels`).
        fingerprint: See `compute_fingerprint` — a stable value a future
            issue-filing automation can use to detect "this defeat already
            has an open issue" before creating a duplicate.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    title: str = Field(min_length=1)
    body: str = Field(min_length=1)
    repo: str = Field(min_length=1)
    labels: tuple[str, ...] = Field(min_length=1)
    fingerprint: str = Field(min_length=1)


def _find_trial(report: MatchReport, trial_id: str | None) -> TrialReport | None:
    """The `TrialReport` in `report.trials` matching `trial_id`, or `None`
    when `trial_id` is `None` (an unattributed classification) or — in
    principle only, since every `trial_id` `classify_defeats` produces comes
    straight from `report.trials` itself — no longer present in `report`.
    """
    if trial_id is None:
        return None
    for trial in report.trials:
        if trial.trial_id == trial_id:
            return trial
    return None


def _policy_ids_for_trial(trial: TrialReport | None) -> tuple[str, ...]:
    """Every distinct, non-`None` `DefenseDecision.policy_id` recorded across
    `trial`'s audit events, sorted for determinism. Empty when `trial` is
    `None` or none of its audit events report a policy id.
    """
    if trial is None:
        return ()
    policy_ids = {
        event.decision.policy_id
        for event in trial.audit_events
        if event.decision is not None and event.decision.policy_id is not None
    }
    return tuple(sorted(policy_ids))


def compute_fingerprint(classification: DefeatClassification, report: MatchReport) -> str:
    """A stable, deterministic fingerprint for `classification`, for
    duplicate-issue detection. See the module docstring's "Duplicate-issue-
    prevention fingerprint strategy" section for exactly which fields feed
    this and why.
    """
    trial = _find_trial(report, classification.trial_id)
    policy_ids = _policy_ids_for_trial(trial)
    fields = "|".join(
        (
            report.scenario_id,
            classification.trial_id or "unattributed",
            classification.category.value,
            classification.detail,
            ",".join(policy_ids),
        )
    )
    return hashlib.sha256(fields.encode("utf-8")).hexdigest()


def _expected_and_actual(trial: TrialReport | None) -> tuple[str, str]:
    """`(expected, actual)` decision summaries for an issue body, one
    `tool=decision` pair per line item, comma-joined.

    `expected` comes straight from `TrialReport.expected` (every tool the
    trial declared an expectation for). `actual` comes from the trial's own
    `audit_events`: a `DECIDED` event's `decision.effect`, or the literal
    "no decision recorded" for a `MISSING_DECISION` event — so a reader can
    see exactly what agent-assembly rendered (or failed to render) for each
    attempted tool, not just the one tool a specific classification signal
    happened to be about.
    """
    if trial is None:
        return "N/A (no attributable trial)", "N/A (no attributable trial)"

    expected = ", ".join(
        f"{tool}={decision.value}" for tool, decision in sorted(trial.expected.items())
    )

    actual_by_tool: dict[str, str] = {}
    for event in trial.audit_events:
        if event.attempt is None:
            continue
        if event.decision is not None:
            actual_by_tool[event.attempt.tool] = event.decision.effect.value
        elif event.status is AuditEventStatus.MISSING_DECISION:
            actual_by_tool[event.attempt.tool] = "no decision recorded"
    actual = ", ".join(f"{tool}={effect}" for tool, effect in sorted(actual_by_tool.items()))

    return expected or "N/A (trial declared no expectations)", actual or "N/A (no audit events)"


def _agent_framework(trial: TrialReport | None) -> str:
    """The `ArenaActionAttempt.framework` of `trial`'s first audit event
    with an attempt, or `"N/A"` when `trial` is `None` or has no such event.
    Every attempt within one trial shares the same agent/framework (see
    `arena.reports.generate.build_report`'s `(agent_id, trial_id)` grouping),
    so the first one found is representative.
    """
    if trial is None:
        return "N/A"
    for event in trial.audit_events:
        if event.attempt is not None:
            return event.attempt.framework
    return "N/A"


def build_issue_payload(
    classification: DefeatClassification, routing: DefeatRouting, report: MatchReport
) -> IssuePayload:
    """Build the `IssuePayload` for one `classification`, already routed via
    `route_defeat` against `report`.

    Title: `routing.title_prefix` (already ends in a colon and space, e.g.
    `"[Arena Defeat] Critical escape: "` — see `defeat_routing.yaml`) plus
    `<scenario_id>/<trial_id>` (or `/unattributed` when `classification` has
    no `trial_id`), so every issue title is unique per (scenario, trial,
    category) and unambiguous at a glance in a repo's issue list.

    Body: a Markdown evidence block carrying every field AAASM-4402's AC
    requires — scenario id, match id, agent id/framework, trial id, expected
    vs. actual decision(s), impact/severity, a link to the full report and
    its audit log (see `REPORTS_ROOT`), and the suggested labels.
    """
    trial = _find_trial(report, classification.trial_id)
    expected, actual = _expected_and_actual(trial)
    trial_id_display = classification.trial_id or "unattributed (no specific trial)"
    agent_id_display = classification.agent_id or "N/A"
    report_dir = f"{REPORTS_ROOT}/{report.match_id}"

    title = (
        f"{routing.title_prefix}{report.scenario_id}/{classification.trial_id or 'unattributed'}"
    )

    body = (
        "\n".join(
            (
                f"**Category:** {classification.category.value}",
                f"**Scenario ID:** {report.scenario_id}",
                f"**Match ID:** {report.match_id}",
                f"**Agent ID:** {agent_id_display}",
                f"**Framework:** {_agent_framework(trial)}",
                f"**Trial ID:** {trial_id_display}",
                f"**Expected decision(s):** {expected}",
                f"**Actual decision(s):** {actual}",
                f"**Impact / severity:** {routing.severity.value}",
                "",
                "**Detail:**",
                classification.detail,
                "",
                f"**Full report:** {report_dir}/arena-report.md",
                f"**Audit log:** {report_dir}/audit.jsonl",
                "",
                f"**Suggested labels:** {', '.join(routing.labels)}",
            )
        )
        + "\n"
    )

    return IssuePayload(
        title=title,
        body=body,
        repo=routing.repo,
        labels=routing.labels,
        fingerprint=compute_fingerprint(classification, report),
    )


def build_issue_payloads_for_report(report: MatchReport) -> list[IssuePayload]:
    """`classify_defeats` -> `route_defeat` -> `build_issue_payload` for
    every defeat signal in `report`, using the default (committed)
    `defeat_routing.yaml`. Empty for a winning report — see
    `classify_defeats`'s own docstring for why.
    """
    routing_config = load_defeat_routing_config()
    return [
        build_issue_payload(classification, route_defeat(classification, routing_config), report)
        for classification in classify_defeats(report)
    ]
