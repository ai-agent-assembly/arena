# Running Arena locally

A practical "how do I actually run this" companion to `docs/runners.md`
(which covers *when* Arena picks `ProcessRunner` vs. `DockerRunner` — read
that first if you haven't; this document doesn't repeat it) and
`docs/architecture.md` (the conceptual pipeline). This document covers the
mechanics: prerequisites, copy-pasteable commands, where output lands, and
what to do when something doesn't run.

## Prerequisites

- **uv** — required. Arena is a uv-managed Python project; every command
  below is run through `uv run` so it resolves the project's pinned
  dependencies automatically, with no separate "activate a venv" step.
- **Docker** — optional. Only needed if you're running an agent whose
  manifest declares `entrypoint.type: docker` (community-submitted agents,
  by convention — see `docs/runners.md`). The official demo agent used
  below uses `entrypoint.type: command` and needs no Docker at all.

Install dependencies once per checkout:

```bash
uv sync
```

## Run a match

From the repository root:

```bash
uv run aasm-arena run github-maintainer-dungeon
```

This selects every agent registered under `agents/official/` and
`agents/community/` that declares `github-maintainer-dungeon` in its
manifest's `scenarios` list, runs every trial in the scenario for each of
them, and prints a per-(agent, trial) result table plus a pass/fail summary.

Useful variations:

```bash
# Run only one agent instead of every compatible agent.
uv run aasm-arena run github-maintainer-dungeon --agent raw-python-issue-triager

# Write match output somewhere other than the default ./runs/ directory —
# keep it as a single relative path segment under the repo root, see the
# "can't find its own files" troubleshooting note below for why.
uv run aasm-arena run github-maintainer-dungeon --output-root ./local-runs

# Point at a different scenario/agent registry root (e.g. while developing
# a new scenario or agent outside the repo's own tree).
uv run aasm-arena run my-scenario --scenarios-root ./my-scenarios --official-root ./my-agents
```

`aasm-arena run --help` lists every flag with its default.

**A note on `--output-root`:** every example above was re-run verbatim
before this ticket landed. `--output-root ./local-runs` works exactly like
the default `./runs/` (still a single relative path segment under the repo
root). An **absolute** or **multi-segment** `--output-root` (e.g.
`/tmp/arena-runs` or `./scratch/runs`) still runs Arena's own orchestration
fine, but makes the official `raw-python-issue-triager` demo agent's trials
fail — see "A `command`-type agent can't find its own files" below for
exactly why.

### What actually happens, end to end

1. Arena loads the scenario (and its trials) from `--scenarios-root`, and
   discovers every agent manifest under `--official-root` /
   `--community-root`.
2. For each (agent, trial) pair, Arena resolves the agent's
   `entrypoint.type` to a `Runner` (`ProcessRunner` for `command`,
   `DockerRunner` for `docker` — see `docs/runners.md`) and asks it to
   actually run the agent: `ProcessRunner` launches a real local
   subprocess; `DockerRunner` launches a real `docker run` container. Both
   are genuine execution — nothing here is mocked.
3. The agent process/container receives trial context via environment
   variables (`ARENA_AGENT_ID`, `ARENA_TRIAL_ID`, `ARENA_TRIAL_DESCRIPTION`,
   `ARENA_TRIAL_SEVERITY`, `ARENA_WORKSPACE` — see the "Context delivery"
   section of `arena.runner.process`'s module docstring) and does whatever
   its own code does.
4. Arena records the exit code, stdout/stderr, and duration for every
   (agent, trial) pair, and prints a summary table plus a match verdict.

### Where output lands

Each match creates one workspace directory under `--output-root` (`./runs/`
by default), named `<UTC timestamp>-<scenario-id>-<random suffix>`. Beneath
that, one subdirectory per `<agent-id>/<trial-id>` is created — this is the
`cwd` each agent process/container actually runs in (see "Working
directory" caveat below).

```
runs/
  20260710T072905Z-github-maintainer-dungeon-a9ac75b9/
    raw-python-issue-triager/
      issue-triage-happy-path/
      prompt-injection-code-write/
      secret-leak-attempt/
      release-publish-requires-approval/
      destructive-command-drop/
```

Report rendering (Markdown/JSON/JSONL, per `docs/architecture.md`'s
"Report" pipeline stage) is not implemented yet — today the CLI's own
printed table and exit code are the only output; the workspace directories
above exist for the agent to run in, not (yet) as a place Arena itself
writes a report to.

## What's mocked vs. real, today

- **Execution is real.** `ProcessRunner` and `DockerRunner` are genuine
  execution backends (AAASM-4374/4375) — no scenario run is simulated.
- **Scoring is a placeholder proxy.** Until AAASM-4377 wires in real
  agent-assembly governance decisions, Arena has no way to know what
  agent-assembly *would* have decided for a given action. `TrialOutcome.passed`
  is therefore only `exit_code == 0` — a proxy, not a real allow/deny
  comparison against the trial's `expected` field (see the module docstring
  in `arena.runner.match`). **A "PASS" in the CLI's output table today only
  means the agent process exited 0 — it is not a governance verdict.**
  Running the `github-maintainer-dungeon` scenario against the official
  `raw-python-issue-triager` agent currently shows every trial, including
  the adversarial ones (prompt injection, secret leak, unapproved release,
  destructive command), as PASS — that is an artifact of this proxy, not
  evidence that anything was actually governed. A real red/green signal for
  those trials only exists once AAASM-4377 lands.
- **`NoOpRunner`** (`arena.runner.noop`) still exists and is still used by
  parts of the test suite that want a `Runner` with zero side effects, but
  it is no longer part of `default_runner_registry()` — a real `aasm-arena
  run` invocation never uses it.

## Troubleshooting

**"Docker not installed" / daemon not running.** `DockerRunner` only
matters if you're running a `docker`-type agent. If you don't have Docker
installed or the daemon isn't running, `DockerRunner` reports that failure
as a normal non-zero `AgentRunResult` for the affected trial(s) — it does
not crash `aasm-arena run` — because it shells out through the `docker` CLI
rather than talking to the daemon directly. `docs/runners.md`'s "How it's
tested" section explains why the daemon doesn't even need to be running for
`DockerRunner`'s own test suite; the same graceful-failure behavior applies
to a live local run against an agent you don't have Docker set up for. Fix:
install Docker Desktop (or your platform's docker CLI + daemon), or run
only the `command`-type agents you care about with `--agent`.

**A `ProcessRunner` timeout.** `ProcessRunner` bounds every agent process to
`DEFAULT_TIMEOUT_SECONDS` (30s) by default. A trial that hits this shows up
with exit code `124` and a stderr line like:

```
[arena.ProcessRunner] agent process timed out after 30.0s (command=...); this is a runner-enforced timeout, not a real process exit
```

This is expected, deliberate behavior for a hung/looping agent — one stuck
agent process can't stall the whole match. There's no `--timeout` CLI flag
yet; if you need a longer budget for local experimentation, construct a
`ProcessRunner(timeout_seconds=...)` directly via the Python API
(`arena.runner.process.ProcessRunner`) instead of the CLI.

**A `command`-type agent can't find its own files.** `ProcessRunner`
launches the agent's `entrypoint.command` with `cwd` set to that
(agent, trial)'s workspace directory (see "Where output lands" above), *not*
the agent's own submission directory — `Runner.run` has no path field to
tell it where that is. A relative path in `entrypoint.command` (like plain
`main.py`) therefore will not find a same-named file sitting next to
`agent.yaml`. See the comment in
`agents/official/raw-python-issue-triager/agent.yaml` for how the official
demo agent works around this (a `../../../../`-relative offset back to the
repo root, valid only for the documented default `--output-root=runs`
invoked from the repo root) — and reference `tests/test_smoke_local_run.py`
for a more portable pattern (an absolute-path command) if you're writing a
new agent and don't want that constraint.

**`scenarios validate` before you run.** If a scenario or trial YAML file
doesn't load, `aasm-arena run` fails fast with a load error rather than a
partial run. Validate independently first:

```bash
uv run aasm-arena scenarios validate scenarios/github-maintainer-dungeon
```

## Smoke tests

`tests/test_smoke_local_run.py` is the automated version of "does a local
match skeleton actually run" — it drives `aasm-arena run` through Typer's
`CliRunner` against a small, self-contained, dedicated no-op scenario/agent
fixture (not the real `github-maintainer-dungeon` scenario) written under
pytest's `tmp_path`, so it needs no external services, no secrets, and no
live Docker daemon, and stays fast. `tests/test_cli_run.py` separately
exercises the real `github-maintainer-dungeon` scenario end to end (see its
own docstrings for why that test intentionally still expects the official
agent's trials to fail there — an external `tmp_path` output root doesn't
satisfy the offset described above).

Run it directly:

```bash
uv run pytest tests/test_smoke_local_run.py -v
```
