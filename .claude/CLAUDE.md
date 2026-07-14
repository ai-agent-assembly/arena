# CLAUDE.md — arena

Guidance for Claude Code (and humans) working in this repository. This file holds
**repo-specific** context only; universal engineering policy lives in the global
config. When a fact here duplicates `README.md`, `pyproject.toml`, or a CI
workflow, treat those as the source of truth and update them, not just this file.

Org-wide baseline: https://github.com/ai-agent-assembly/.github/blob/main/CLAUDE.md
(org-universal conventions this file doesn't repeat).

## What this repo is

**Arena** is the public trial ground for agent-assembly governance: agents enter,
agent-assembly defends, and every match leaves a report. Arena is an
**orchestrator, not a governance engine** — it loads agent plugins, runs them
through scenario/trial definitions, and records the resulting decisions; every
allow/deny/approve/quarantine/redact call comes from
[agent-assembly](https://github.com/ai-agent-assembly/agent-assembly) itself, not
from Arena's own logic. It is also not `examples`: `examples` is small,
framework-specific integration snippets, while Arena runs full cross-framework
governance trials (adversarial scenarios, behavior profiles, deterministic
mock/replay agents) and publishes match reports. See `docs/architecture.md` for
the full conceptual write-up — this section is a summary of it.

### The pipeline: manifest → scenario/trial → runner → report

1. **Manifest** — a declarative description of how to build/run an agent, which
   framework it's on, and which scenarios it's eligible for. Arena never imports
   or hard-codes agent-specific logic; it only reads manifests.
2. **Scenario / Trial** — a scenario (e.g. `github-maintainer-dungeon`) is a
   themed setting made of one or more trials: individual, scored situations
   (happy-path, prompt-injection, secret-leak attempt, an action that should
   require approval, a destructive command that should be dropped/quarantined).
3. **Runner** — builds/starts the agent per its manifest inside a sandbox
   boundary (Docker or an isolated process), feeds it the scenario's trials, and
   observes both the agent's attempted actions and agent-assembly's decisions.
   The sandbox matters most for community-submitted agents: submitted plugin
   code never gets repository secrets or elevated credentials.
4. **Report** — every match produces `arena-report.json`/`.md` plus an
   `audit.jsonl`, describing what was attempted, what agent-assembly decided,
   and whether the match is a win or a loss.

## Build, test, lint

Python ≥ 3.12, managed with `uv`. CLI entry point: `aasm-arena = "arena.cli:app"`.

```bash
uv sync                              # install runtime + dev deps
uv run pytest                        # full suite (testpaths = tests/)
uv run ruff check .                  # lint
uv run ruff format --check .         # format check
uv run mypy src                      # strict type-check (mypy_path = src)
uv sync --group docs                 # docs toolchain (mkdocs-material, mike, ...)
uv run mkdocs build --strict         # docs build gate (CI runs this on every PR)
```

`uv run aasm-arena --help` lists CLI subcommands: `run`, `scaffold-agent`,
`agents` (subgroup), `scenarios validate`, `reports defeat-issues`, plus
`version`/`hello`.

## Source layout

```
src/arena/               # core package (agents, integrations, models, registry,
                          # reporting, reports, runner, scenarios, cli.py)
agents/official/          # first-party deterministic agents (ci-debug-agent,
                          # langgraph-docs-agent, mock-malicious-agent,
                          # raw-python-issue-triager, release-agent)
agents/community/         # public submissions, landed via PR; run sandboxed,
                          # never given repo secrets — see
                          # .github/workflows/validate-community-agents.yml
scenarios/                # scenario/trial definitions, e.g. github-maintainer-dungeon
templates/agent-plugin/   # scaffold used by `aasm-arena scaffold-agent`
reports/                  # generated match output + a tracked "static index"
                          # (latest.json, latest.md, leaderboard.json) refreshed
                          # by every match — see reports/README.md for the schema
scripts/                  # render_agents_scenarios_page.py, render_latest_reports_page.py,
                          # generate_report_samples.py — used by documentation.yml
                          # to regenerate docs pages from live data before mkdocs build
docs/                     # mkdocs-material site, deployed to
                          # docs.agent-assembly.com/arena via mike on push to main
```

## Facts a future session needs (not obvious from reading one file)

- **Agent → Arena stdout marker protocol.** A governed agent subprocess reports
  each action attempt by printing a JSON line prefixed with
  `arena.integrations.emit.ACTION_ATTEMPT_MARKER_PREFIX` to stdout.
  `AgentRunResult.stdout` captures the whole blob, mixed with ordinary agent
  output; `arena.integrations.parser.parse_action_attempts` scans it line by
  line, recovering an `ArenaActionAttempt` from every marker-prefixed line.
  Malformed markers (bad JSON, failed `ArenaActionAttempt` validation) are
  recorded as errors and **skipped, not raised** — one broken marker line must
  not prevent every other real attempt in the same output from being recovered.
- **Fail-closed governance contract (AAASM-4381).** Every `AgentAssemblyClient`
  implementation must, for every action attempt, either return a
  `DefenseDecision` or raise `MissingDecisionError` — it must never return
  `None` or silently default to an allow-shaped outcome.
  `arena.runner.match.run_match` treats a raised `MissingDecisionError` as a
  recorded `ArenaAuditEvent` with `status=MISSING_DECISION`, and
  `_trial_expectations_satisfied` (`arena.runner.match`) means a trial can
  **never pass** while any of its attempts are in that state. This is
  deliberate: defaulting a missing decision to allow would itself be a
  governance bypass. See `docs/architecture.md`'s "minimum decision contract"
  section and `tests/test_integrations_contract.py` for the adversarial tests
  that protect it.
- **`Decision.REDACT` is the only signal that triggers persisted-args
  redaction.** `arena.integrations.audit.append_audit_event` obscures every
  value in the *persisted* (JSONL) copy of `attempt.args` — never the
  in-memory object — specifically and only when `decision.effect is
  Decision.REDACT`. `obligations` free text is not pattern-matched for this.
- **`SCHEMA_VERSION` bump convention.** `arena.reports.models.SCHEMA_VERSION`
  (currently `"2"`) is a plain string, bumped deliberately whenever
  `MatchReport`'s shape changes in a way that breaks old payloads — e.g.
  `"1"` → `"2"` added a new *required* `execution` field
  (`ExecutionMetadata`), so old schema-`"1"` payloads no longer validate at
  all. The companion index schemas
  (`arena.reports.index.LATEST_INDEX_SCHEMA_VERSION` /
  `LEADERBOARD_SCHEMA_VERSION`) follow the same convention independently.
  Treat a bump as a deliberate, visible schema change — update the constant's
  docstring and cross-check `docs/report-schema.md`.
- **`reports/` on `main` is generated but tracked in git** — the
  `scheduled-matches` workflow runs real matches on a schedule and commits the
  refreshed `latest.json`/`latest.md`/`leaderboard.json`/`matches/` back to
  `main`, so a docs/website consumer can fetch current match history via a
  plain HTTP GET, no Arena install or backend service required.

## CI

- `ci.yml` — lint (`ruff check`), format check (`ruff format --check`),
  `mypy src`, `pytest`, then a "schema smoke check" that just imports every
  `arena` subpackage (AAASM-4363: real Pydantic schema validation for
  manifests/scenarios/reports lands in later tickets; until then this only
  catches broken imports/syntax errors).
- `documentation.yml` — PRs run `mkdocs build --strict` build-only (never
  deploys). Pushes to `main` regenerate `docs/agents-scenarios.md` and
  `docs/latest-reports.md` from live data via `scripts/`, then deploy the
  "latest" channel to `gh-pages` via `mike`.
- `validate-community-agents.yml` — validates `agents/community/` submissions
  in a way that keeps untrusted PR code out of any privileged context.
- `scheduled-matches.yml` — runs real matches on a schedule (and on manual
  `workflow_dispatch`), refreshing `reports/` on `main`.

## Repo-specific gotchas

- **Default branch is `main`** (not `master`). Branch off and PR against `main`.
- **Canonical/push remote is `origin`** — points at `ai-agent-assembly/arena`.
  Confirm with `git remote -v`.
- **No lefthook / pre-commit config in this repo** — the only local gates are
  the commands above; nothing to `install` before committing.
- **`reports/` other than `README.md` is generated output**, not hand-authored
  — don't hand-edit `latest.json`/`latest.md`/`leaderboard.json`/`matches/`.

## Project policy

- **JIRA:** project AAASM; set **Component** (`customfield_10041`) to
  `ai-agent-assembly/arena`; Team (`customfield_10001`) = Pioneer.
  Epic → Story → Subtask (one Subtask ≈ one commit) + a `Verify …` subtask per
  Story.
- **Self-hosted deployment is out of scope** product-wide — don't add
  Helm/Terraform/air-gapped instructions even if a request implies them.
- **The Protocol Specification stays in the `agent-assembly` monorepo** — Arena
  consumes agent-assembly's governance decisions, it does not define policy
  semantics itself.
