"""File real GitHub issues for routed Arena defeats via the `gh` CLI (AAASM-4505).

This is the follow-up to AAASM-4402's `arena.reports.issue_payload`, which
builds the `IssuePayload`(s) a defeat *would* produce but deliberately never
calls the GitHub API. This module is where that boundary is finally crossed:
`create_issues_for_report` actually shells out to `gh issue create` for each
payload, targeting `payload.repo` — which, for the `critical_escape`/
`unexpected_allow`/`secret_exposure`/`approval_bypass`/`missing_audit`/
`quarantine_failure` categories, is `ai-agent-assembly/agent-assembly`, a
*different* repo than the one this code runs in (see `defeat_routing.yaml`).

**Why shell out to `gh` instead of a Python GitHub client.** `gh` is already
the tool this org's CI/tooling uses everywhere else (see e.g.
`.github/workflows/*.yml`), already handles auth via `GH_TOKEN`/
`GITHUB_TOKEN`, and needs no new dependency in `pyproject.toml`. Every call
here goes through `subprocess.run`, injected as `command_runner` — the same
constructor/parameter-injection seam `arena.runner.docker.DockerRunner` and
`arena.runner.process.ProcessRunner` use, so tests exercise the exact argv
this module builds without a real `gh` binary, a real token, or a network
call (see `tests/test_reports_github_issues.py`).

**Token handling.** `gh` itself reads `GH_TOKEN` (checked first) or
`GITHUB_TOKEN` (fallback) from the process environment to authenticate non-
interactively — this module does not set either var itself, it only checks
that one is present *before* shelling out, so a missing token fails with one
clear, actionable message instead of `gh`'s own auth error surfacing from
deep inside a subprocess call (or, worse, silently no-op-ing). In
`.github/workflows/scheduled-matches.yml` that value comes from the
`ARENA_DEFEAT_ISSUE_TOKEN` repository secret — a dedicated token, not the
default `GITHUB_TOKEN` Actions provides, because filing into
`ai-agent-assembly/agent-assembly` from a workflow running in this
(`arena`) repo needs `issues:write` on *both* repos, which the default
per-repo `GITHUB_TOKEN` cannot grant. See `reports/README.md` for the full
setup note (a manual, out-of-band repo-admin action — this module never
creates or stores that secret itself).

**Duplicate-issue-prevention.** `IssuePayload.fingerprint` (AAASM-4402,
`arena.reports.issue_payload.compute_fingerprint`) is embedded as a hidden
HTML comment (`<!-- arena-fingerprint: <hash> -->`) at the end of the issue
body before creation. Before filing, `find_existing_issue` searches the
target repo for an **open** issue whose body already contains that exact
fingerprint (`gh issue list --search "<fingerprint> in:body" --state open`)
— HTML comments don't render on GitHub but are indexed by its search, so
this is invisible to a human reading the issue while still being a reliable
machine-readable dedup key. A match skips creation entirely rather than
erroring — a repeat defeat with an already-open issue is the expected,
common case, not a failure.
"""

from __future__ import annotations

import json
import os
import subprocess
from collections.abc import Callable
from dataclasses import dataclass

from arena.reports.issue_payload import IssuePayload

#: Injectable seam so tests can exercise this module without a real `gh`
#: binary, a real token, or a network call — mirrors
#: `arena.runner.docker.CommandRunner`.
CommandRunner = Callable[..., "subprocess.CompletedProcess[str]"]

#: Env vars `gh` itself reads for non-interactive auth, in the order `gh`
#: checks them (see `gh help environment`). This module only *reads* these
#: to fail fast with a clear message — it never sets them; `gh` picks them
#: up from the inherited subprocess environment on its own.
GH_TOKEN_ENV_VAR = "GH_TOKEN"
GH_TOKEN_FALLBACK_ENV_VAR = "GITHUB_TOKEN"

#: Prefix for the hidden HTML-comment dedup marker appended to every issue
#: body. See the module docstring's "Duplicate-issue-prevention" section.
FINGERPRINT_MARKER_PREFIX = "<!-- arena-fingerprint:"


class GitHubIssueCreationError(Exception):
    """Raised when live issue creation cannot proceed, or `gh` itself fails.

    Covers both a missing token (checked before any `gh` call is made) and a
    non-zero exit from `gh issue list`/`gh issue create` (auth rejected,
    repo not found, rate-limited, etc.) — in both cases the caller (the
    `defeat-issues --no-dry-run` CLI command) surfaces `str(exc)` directly
    rather than an opaque stack trace.
    """


@dataclass(frozen=True)
class IssueCreationResult:
    """The outcome of attempting to file one `IssuePayload`.

    Fields:
        payload: The `IssuePayload` this result is for.
        skipped_duplicate: `True` when an open issue already carried this
            payload's fingerprint and no new issue was created.
        issue_url: The (new or pre-existing) issue's URL.
    """

    payload: IssuePayload
    skipped_duplicate: bool
    issue_url: str


def _fingerprint_marker(fingerprint: str) -> str:
    return f"{FINGERPRINT_MARKER_PREFIX} {fingerprint} -->"


def _require_gh_token() -> None:
    """Fail fast, before any `gh` call, when neither auth env var is set.

    Deliberately checked once per `create_issues_for_report` call (not per
    payload) so a misconfigured workflow fails on its first attempt rather
    than partway through filing several issues.
    """
    if os.environ.get(GH_TOKEN_ENV_VAR) or os.environ.get(GH_TOKEN_FALLBACK_ENV_VAR):
        return
    raise GitHubIssueCreationError(
        "Live GitHub issue creation requires a token in the "
        f"{GH_TOKEN_ENV_VAR} (or {GH_TOKEN_FALLBACK_ENV_VAR}) environment variable, "
        "for the `gh` CLI to authenticate with — none is set. In "
        ".github/workflows/scheduled-matches.yml this is sourced from the "
        "ARENA_DEFEAT_ISSUE_TOKEN repository secret (see reports/README.md for setup); "
        f"locally, export {GH_TOKEN_ENV_VAR} with a token that has issues:write on the "
        "target repo before retrying."
    )


def find_existing_issue(
    payload: IssuePayload, *, command_runner: CommandRunner = subprocess.run
) -> str | None:
    """The URL of an already-open issue in `payload.repo` carrying
    `payload.fingerprint`'s dedup marker, or `None` when none is found.

    Raises `GitHubIssueCreationError` when `gh issue list` itself fails
    (non-zero exit) or returns output this function cannot parse as the
    `--json number,url` array it asked for.
    """
    completed = command_runner(
        [
            "gh",
            "issue",
            "list",
            "--repo",
            payload.repo,
            "--search",
            f"{payload.fingerprint} in:body",
            "--state",
            "open",
            "--json",
            "number,url",
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    if completed.returncode != 0:
        raise GitHubIssueCreationError(
            f"`gh issue list` failed for {payload.repo!r}: {completed.stderr.strip()}"
        )

    try:
        issues = json.loads(completed.stdout or "[]")
    except json.JSONDecodeError as exc:
        raise GitHubIssueCreationError(
            f"`gh issue list` for {payload.repo!r} returned unparseable JSON: {exc}"
        ) from exc

    if not issues:
        return None

    url = issues[0].get("url")
    if not isinstance(url, str):
        raise GitHubIssueCreationError(
            f"`gh issue list` for {payload.repo!r} returned an issue with no url: {issues[0]!r}"
        )
    if not url:
        raise GitHubIssueCreationError(
            f"`gh issue list` for {payload.repo!r} returned an issue with an empty url."
        )
    return url


def create_issue_for_payload(
    payload: IssuePayload, *, command_runner: CommandRunner = subprocess.run
) -> IssueCreationResult:
    """File `payload` as a real GitHub issue via `gh issue create`, unless
    `find_existing_issue` already finds an open duplicate — in which case
    creation is skipped and the existing issue's URL is returned instead.

    Does **not** call `_require_gh_token` itself — `create_issues_for_report`
    checks once for the whole batch (see its own docstring for why).
    """
    existing_url = find_existing_issue(payload, command_runner=command_runner)
    if existing_url is not None:
        return IssueCreationResult(payload=payload, skipped_duplicate=True, issue_url=existing_url)

    body = f"{payload.body}\n{_fingerprint_marker(payload.fingerprint)}\n"
    args = [
        "gh",
        "issue",
        "create",
        "--repo",
        payload.repo,
        "--title",
        payload.title,
        "--body",
        body,
    ]
    for label in payload.labels:
        args.extend(["--label", label])

    completed = command_runner(args, capture_output=True, text=True, check=False)
    if completed.returncode != 0:
        raise GitHubIssueCreationError(
            f"`gh issue create` failed for {payload.repo!r}: {completed.stderr.strip()}"
        )

    issue_url = completed.stdout.strip()
    if not issue_url:
        raise GitHubIssueCreationError(
            f"`gh issue create` for {payload.repo!r} succeeded but printed no issue URL."
        )
    return IssueCreationResult(payload=payload, skipped_duplicate=False, issue_url=issue_url)


def create_issues_for_report(
    payloads: list[IssuePayload], *, command_runner: CommandRunner = subprocess.run
) -> list[IssueCreationResult]:
    """`create_issue_for_payload` for every payload in `payloads`, in order.

    Returns `[]` immediately — without checking for a token or invoking
    `command_runner` at all — when `payloads` is empty (a winning match's
    `build_issue_payloads_for_report()` result), so a winning match's
    `defeat-issues --no-dry-run` run makes zero GitHub API calls and never
    requires a token to be configured.
    """
    if not payloads:
        return []
    _require_gh_token()
    return [
        create_issue_for_payload(payload, command_runner=command_runner) for payload in payloads
    ]
