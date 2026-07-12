---
name: submit-arena-agent
description: Walk a contributor through submitting a new agent plugin to the arena repo via PR — scaffolding, writing agent.yaml and the entrypoint, validating locally, running a real match, and opening the submission PR. Use when someone wants to add/submit/contribute a new agent to Arena's agents/community/ directory.
---

# Submit an Arena agent (PR path)

This skill walks through the **PR-based** agent-submission flow: writing an
agent plugin under `agents/community/<agent-id>/` and opening a pull request
against `main` in `ai-agent-assembly/arena`. It complements
`docs/submit-agent.md` (the canonical human-facing guide) — read that too if
anything here seems to disagree with it, since the doc is the source of
truth and this skill can drift.

This is **not** the right skill for the separate GitHub-Issue-Forms request
path (proposing an agent without writing the plugin yourself — see
`docs/get-involved.md`, "Request an agent be added"). That path opens an
issue from `https://github.com/ai-agent-assembly/arena/issues/new?template=submit-agent.yml`
and does not involve any of the steps below.

Run every command from the `arena` repo root unless noted otherwise.

## 1. Gather requirements

Before writing anything, pin down:

- **Agent id** — lowercase kebab-case, matching
  `AGENT_ID_PATTERN = r"^[a-z0-9]+(-[a-z0-9]+)*$"` in
  `src/arena/models/manifest.py`, 2-64 characters, and unique across
  `agents/official/` and `agents/community/` (check both:
  `ls agents/official agents/community`).
- **Framework** — one of the real `AgentFramework` enum values in
  `src/arena/models/manifest.py`: `raw-python`, `langgraph`, `crewai`,
  `pydantic-ai`, `autogen`, or `other` if the framework isn't listed.
- **Target scenario(s)** — real scenario id(s) under `scenarios/`. Today
  there is exactly one registered scenario:
  `scenarios/github-maintainer-dungeon/` (id `github-maintainer-dungeon`,
  five trials: `issue-triage-happy-path`, `prompt-injection-code-write`,
  `secret-leak-attempt`, `release-publish-requires-approval`,
  `destructive-command-drop` — see
  `scenarios/github-maintainer-dungeon/scenario.yaml`). Confirm the current
  set with `uv run aasm-arena scenarios validate scenarios/` before
  assuming this list is still accurate.
- **Behavior profile(s)** (optional) — if the agent should demonstrate more
  than one distinct posture (e.g. `normal` vs.
  `prompt-injection-vulnerable` vs. `secret-seeking`), plan the
  `BehaviorProfile` list now: each has a required `id` (same kebab-case
  pattern, 2-64 chars) and a required non-empty `description`. See
  `docs/behavior-profiles.md` and `src/arena/models/manifest.py`'s
  `BehaviorProfile`/`AgentManifest.behaviors`. A trial can optionally target
  one via `TrialSpec.behavior_id` (`src/arena/models/scenario.py`) — but as
  of AAASM-4404 this is schema/validation only; nothing at runtime yet
  dispatches an agent into a specific behavior. Declaring behaviors is
  documentation of the agent's distinct postures, not yet a runtime switch.

## 2. Scaffold the agent folder

```bash
uv run aasm-arena scaffold-agent --id <agent-id> --framework <framework>
```

This creates `agents/community/<agent-id>/` (override the parent directory
with `--output`, default `agents/community`) containing a starter
`agent.yaml`, `README.md`, and `main.py`, rendered from
`templates/agent-plugin/*.tmpl`. It fails if `--id` doesn't match the id
pattern, `--framework` isn't a real `AgentFramework` value, or the target
directory already exists.

The scaffolded `agent.yaml` has `scenarios: [REPLACE-WITH-SCENARIO-ID]` —
you must replace that placeholder with a real scenario id before the
manifest validates (see step 3).

## 3. Author the manifest (`agent.yaml`)

Schema is `AgentManifest` in `src/arena/models/manifest.py`
(`model_config = ConfigDict(extra="forbid")` — no invented fields).

Required fields:

- `id` — must equal the folder name under `agents/community/`.
- `name` — human-readable display name.
- `framework` — the `AgentFramework` value from step 1.
- `entrypoint` — `AgentEntrypoint`:
  - `type: command` or `type: docker`.
  - `command` — required when `type: command`.
  - `image` — required when `type: docker`.
  - `env` — optional `dict[str, str]` of extra env vars.
- `runtime` — `AgentRuntime` with `type: process` or `type: container` (the
  sandbox boundary the runner executes the agent inside; see
  `docs/architecture.md`, "Where sandboxing sits").
- `scenarios` — `list[str]`, at least one real scenario id, no blank
  entries.

Optional fields:

- `author` — `AgentAuthor`: `github`, `name`, `contact`, all optional.
- `capabilities` — `list[str]`, defaults to empty. List only what the agent
  actually attempts (e.g. `github.issue.read`, `shell.exec`,
  `secrets.read`) — this is reviewed against `main.py`'s actual
  `emit_action_attempt` calls (see step 4 and `docs/submit-agent.md`'s
  "Safety" checklist).
- `behaviors` — `list[BehaviorProfile]`, defaults to empty. Each entry:
  `id` (kebab-case) + `description` (non-empty). No implicit `normal` entry
  is injected — declare every profile explicitly. Duplicate ids fail
  validation.

**A critical `entrypoint.command` gotcha** (see `docs/local-execution.md`,
"A `command`-type agent can't find its own files"): `ProcessRunner` starts
the command with `cwd` set to that (agent, trial)'s per-run workspace
directory, **not** the agent's own submission directory. A plain relative
command like `"uv run python main.py"` (what the scaffold template writes)
will not find `main.py` unless you fix it up. Two real, working patterns
from this repo:

- **Repo-root-relative offset** (what the official agents do) — e.g.
  `agents/official/raw-python-issue-triager/agent.yaml`:
  `command: "uv run python ../../../../agents/official/raw-python-issue-triager/main.py"`.
  This only works for the documented default `--output-root=runs` invoked
  from the repo root (4 path segments deep:
  `<output-root>/<match-id>/<agent-id>/<trial-id>/`) — it breaks if that
  nesting depth or `--output-root` ever changes. For a community submission
  the equivalent would be
  `agents/community/<agent-id>/main.py` reached the same way.
- **Absolute-path command** (more portable — see
  `tests/test_smoke_local_run.py`'s `_write_noop_agent`): build the command
  with an absolute path to the script, e.g. (Python, building the string
  yourself) `f"{sys.executable} {script_path.resolve()}"`. This resolves
  correctly regardless of where the trial workspace ends up, at the cost of
  the manifest being machine-specific unless you compute the path at
  scaffold/commit time relative to a known repo checkout.

Worked examples to read in full before writing your own:

- `agents/official/raw-python-issue-triager/agent.yaml` +
  `agents/official/raw-python-issue-triager/main.py` — simplest shape, no
  framework dependency, `framework: raw-python`.
- `agents/official/langgraph-docs-agent/agent.yaml` +
  `agents/official/langgraph-docs-agent/main.py` — a real LangGraph
  `StateGraph`, `framework: langgraph`; also see
  `agents/official/ci-debug-agent/` for a second framework-based example.

## 4. Write the entrypoint (`main.py` or Docker)

The runner captures the agent process's full stdout verbatim
(`AgentRunResult`). An agent declares each action it attempts by calling
`emit_action_attempt` from `arena.integrations.emit`, which prints one
`ARENA_ACTION_ATTEMPT: <json>` line per call
(`ACTION_ATTEMPT_MARKER_PREFIX = "ARENA_ACTION_ATTEMPT: "`) — a later parse
step (`arena.integrations.parser`) recovers these from captured stdout.
This is framework-agnostic: it only requires the process to print a line,
regardless of what tool-calling machinery runs inside it.

Signature (`src/arena/integrations/emit.py`):

```python
def emit_action_attempt(
    *,
    tool: str,
    resource: str,
    framework: str,
    scenario_id: str,
    args: dict[str, Any] | None = None,
    context: str | None = None,
    agent_id: str | None = None,
    trial_id: str | None = None,
    stream: TextIO = sys.stdout,
) -> ArenaActionAttempt: ...
```

- `agent_id`/`trial_id` default to the `ARENA_AGENT_ID`/`ARENA_TRIAL_ID`
  environment variables `ProcessRunner`/`DockerRunner` already set for every
  agent invocation — a normal call site doesn't pass these explicitly.
- `framework`/`scenario_id` have **no** environment fallback — pass them as
  module-level constants matching the agent's own `agent.yaml` (see
  `_FRAMEWORK`/`_SCENARIO_ID` in the worked examples below).
- Raises `ValueError` if `agent_id`/`trial_id` is missing and the
  corresponding `ARENA_*` env var isn't set (e.g. running the script
  manually outside `ProcessRunner`/`DockerRunner` without supplying ids).

**Deterministic-mode requirement** (`docs/submit-agent.md`): the agent's
trial-id → action mapping must be a static, deterministic dict — no live
network calls, no real LLM/model API calls, no real destructive actions,
even for adversarial trials. Every attempted action — including
adversarial ones like reading a secrets file or running `rm -rf` — is only
ever *declared* via `emit_action_attempt`; nothing in `main.py` should
actually execute a shell command, delete a file, read a real secret, or
make a real network call. `agents/official/mock-malicious-agent/main.py` is
the concrete worked example of this for a deliberately hostile agent: its
`shell.exec` args contain the literal string `"rm -rf /"` purely as
descriptive marker data, never passed to a shell.

Worked pattern (adapted from `raw-python-issue-triager/main.py`): read
`ARENA_AGENT_ID`/`ARENA_TRIAL_ID`/`ARENA_TRIAL_DESCRIPTION`/
`ARENA_TRIAL_SEVERITY`/`ARENA_WORKSPACE` from the environment, look up the
current trial id in a static `dict[str, tuple[...]]` of actions, and call
`emit_action_attempt` once per action:

```python
from arena.integrations.emit import emit_action_attempt

_FRAMEWORK = "raw-python"
_SCENARIO_ID = "github-maintainer-dungeon"

def main() -> None:
    trial_id = os.environ.get("ARENA_TRIAL_ID", "<unknown-trial>")
    emit_action_attempt(
        tool="github.issues.read",
        resource="issues/bug_report_login_timeout.json",
        framework=_FRAMEWORK,
        scenario_id=_SCENARIO_ID,
        context="Naive triage: reading the incoming bug report before acting on it.",
    )
```

## 5. Validate locally

```bash
uv run aasm-arena agents validate agents/community/<agent-id>/agent.yaml
```

or, to validate every agent in the directory at once (also checks that each
manifest's `id` matches its directory name):

```bash
uv run aasm-arena agents validate agents/community/
```

This is schema/folder-structure validation only — it never executes the
declared `entrypoint`, so it's safe to run against untrusted submissions.
Fix every reported error before moving on; a common one is a manifest `id`
that doesn't match its directory name, or a leftover
`REPLACE-WITH-SCENARIO-ID` placeholder from scaffolding.

Also worth running once, to catch scenario/trial YAML problems early:

```bash
uv run aasm-arena scenarios validate scenarios/github-maintainer-dungeon
```

## 6. Run a real match

```bash
uv run aasm-arena run <scenario-id> --agent <agent-id>
```

This actually launches the agent (`ProcessRunner` for `runtime.type:
process`, `DockerRunner` for `runtime.type: container`) through every trial
in the scenario, scores the match (`score_match`), and writes durable
report artifacts under `reports/matches/<match-id>/` (`arena-report.md`,
`arena-report.json`, `audit.jsonl`) — the command prints that path, plus a
per-trial outcome table to the console.

Read the generated `arena-report.md` (or the console table) to sanity-check
that each trial's action(s) actually got emitted as you intended —
especially that `capabilities` in `agent.yaml` matches what `main.py`
really attempts. A non-zero exit / "victory conditions violated" here can
be expected depending on what agent-assembly decided, per `docs/local-execution.md` — a naive
agent that emits an adversarial attempt is *supposed* to look like that;
what matters at this step is confirming the mechanics work (the process
starts, markers get emitted, a report is generated), not that the outcome
is a "win".

If a timeout occurs (`ProcessRunner`'s default 30s budget, exit code
`124`), see `docs/local-execution.md`'s note on `DEFAULT_TIMEOUT_SECONDS`.

## 7. Prep the contribution

- **Branch**: `<version-or-phase>/<ticket-or-topic>/<short-summary>` per
  this org's branch-naming convention (see the repo's/org's contributing
  docs); if there's no ticket for a community submission, use a short
  descriptive slug in place of the ticket segment.
- **Commits**: small, atomic, Gitmoji format
  (`<emoji> <scope>: <imperative summary>`) — see `CONTRIBUTING.md` and the
  repo's real commit history (`git log --oneline`) for the convention in
  practice. Typically `✨` for a new agent submission.
- **PR**: open against `main`, using the **agent-submission** PR template
  (`.github/PULL_REQUEST_TEMPLATE/agent-submission.md`) rather than the
  repo's default template — GitHub picks the default automatically, so
  select this one explicitly by appending `?template=agent-submission.md`
  to the PR-compare URL, or via GitHub's template picker. It asks for:
  - Agent id, framework, target scenario(s).
  - A deterministic-CI-mode confirmation checkbox.
  - Safety notes — what `main.py` actually does per trial, and
    confirmation that no real secrets/shell/network calls are present and
    every attack is declared via `emit_action_attempt` only.
  - Manifest validation confirmation (step 5's command).
  - The Jira ticket link, if any, and related GitHub issues.
- **Review**: `docs/submit-agent.md` ("Security review") — a PR touching
  `agents/community/**` triggers an automated manifest-validation-only CI
  workflow (`.github/workflows/validate-community-agents.yml`); it never
  executes the agent's `entrypoint`. A maintainer runs the agent through a
  real match after merge (or explicit maintainer approval) before it joins
  Arena's scheduled match rotation.
