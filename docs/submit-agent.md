# Submitting an agent plugin via PR

This document is the PR-based contribution path: forking or branching this
repo, adding an agent plugin directly under `agents/community/`, and opening
a pull request. If you'd rather request that an agent be added without
writing the plugin folder yourself, use the GitHub Issue Form (see
`CONTRIBUTING.md`) instead — that's a separate, lighter-weight path.

See `docs/glossary.md` for precise definitions of the terms used below
(Agent/Agent Plugin, Manifest, Scenario, Trial, Capabilities), and
`docs/architecture.md` for how a submitted agent fits into a match.

## Folder structure

Every community agent lives in its own directory, named after the agent's
`id`:

```
agents/community/<agent-id>/
  agent.yaml   # the manifest — required
  main.py      # (or your framework's entrypoint) — whatever agent.yaml's
               # entrypoint.command points at
  README.md    # recommended: what the agent does, how to run it locally
```

`<agent-id>` must be **lowercase kebab-case** — matching
`AgentManifest.id`'s validation pattern in `src/arena/models/manifest.py`:
alphanumeric segments separated by single hyphens, no leading/trailing
hyphen (e.g. `raw-python-issue-triager`, `my-cool-agent`). It must also be
unique across `agents/official/` and `agents/community/`.

This is the same layout `agents/official/` uses — see
`agents/community/README.md`.

## Manifest requirements (`agent.yaml`)

The manifest schema is defined by the `AgentManifest` Pydantic model in
`src/arena/models/manifest.py`. It rejects any field not listed below
(`model_config = ConfigDict(extra="forbid")`), so don't invent extra keys.

Required fields:

- **`id`** (`str`) — must match the agent-id pattern above, 2-64 characters,
  and equal the folder name under `agents/community/`.
- **`name`** (`str`) — a human-readable display name.
- **`framework`** (`AgentFramework` enum) — one of `raw-python`,
  `langgraph`, `crewai`, `pydantic-ai`, `autogen`, or `other` if your
  framework isn't listed.
- **`entrypoint`** (`AgentEntrypoint`) — how the runner starts your agent:
  - `type` — `command` or `docker`.
  - `command` — required when `type: command` (e.g.
    `"uv run python main.py"`).
  - `image` — required when `type: docker`.
  - `env` — optional dict of extra environment variables to pass through.
- **`runtime`** (`AgentRuntime`) — `type: process` or `type: container`; the
  sandbox boundary the runner executes your agent inside (see
  `docs/architecture.md`, "Where sandboxing sits").
- **`scenarios`** (`list[str]`, at least one entry) — the scenario id(s)
  under this repo's `scenarios/` directory your agent is eligible for. No
  blank entries.

Optional fields:

- **`author`** — `github`, `name`, `contact`, all optional strings.
- **`capabilities`** (`list[str]`, defaults to empty) — the governance
  capabilities your agent attempts to use (e.g. `github.issue.read`,
  `shell.exec`, `secrets.read`). List only what your agent's code actually
  attempts — see the "Safety" checklist below.

Validate your manifest locally before opening a PR:

```bash
uv run aasm-arena agents validate agents/community/<agent-id>/agent.yaml
```

## Deterministic-mode expectation

Agents used in Arena scenarios — official and community alike — must behave
**deterministically**: no live network calls, no calls to a real LLM/model
API, and no real destructive actions, even for adversarial/"attack" trials.
This is what keeps matches reproducible in CI without needing external
credentials or nondeterministic model output.

Concretely, this means:

- Your agent's logic (which trial id maps to which action) should be a
  static, deterministic mapping — not a live decision made by calling out to
  a real model or external service.
- Any action your agent "attempts" — including obviously adversarial ones
  like reading a secrets file or running `rm -rf` — is only ever *declared*
  via `arena.integrations.emit.emit_action_attempt`, which prints a
  structured marker line. Nothing in your `main.py` should actually execute
  a shell command, delete a file, read a real secret, or make a real network
  call. Arena's runner and agent-assembly's governance layer are what decide
  what happens with a declared attempt — your agent's job is only to declare
  it truthfully.

`agents/official/mock-malicious-agent/agent.yaml` and its `main.py` are a
concrete worked example of this: it's an intentionally hostile agent (it
declares attempts to read secrets, push directly to `main`, and run a
destructive shell command), but every one of those "attacks" is a hard-coded
`emit_action_attempt(...)` call — nothing it does ever touches a real file,
secret, or shell. Read that file's module docstring for the exact safety
guarantee and how it's tested.

## Security review

Submissions are reviewed by a maintainer before being merged or run as part
of Arena's regular match rotation:

- No real secrets, credentials, or tokens may appear anywhere in a
  submission.
- No code may execute a real destructive command, a real network call, or
  anything else that isn't a declared (not executed) action attempt.
- Submitted PR code is never run with repository secrets or elevated CI
  credentials, and match execution always happens inside the runner's
  sandboxed execution boundary (Docker or an isolated process, per your
  manifest's `runtime.type`) — see `docs/architecture.md` and
  `CONTRIBUTING.md`'s "Security: untrusted code and secrets" section.
- Automated CI on a submission PR performs static/schema validation (lint,
  type-check, manifest/scenario schema checks) — it does not execute
  arbitrary untrusted agent code as part of the PR checks. A maintainer runs
  the agent through a full match, after merge or explicit maintainer
  approval, before it becomes part of Arena's regular rotation.

## Worked examples

Two existing official agents illustrate the two most common shapes. Both
follow the deterministic-mode rule above; read their manifests and
`main.py`/`README.md` for the full pattern rather than duplicating them
here.

### Raw Python agent

`agents/official/raw-python-issue-triager/` — a plain Python script (no
framework dependency), `framework: raw-python`, `entrypoint.type: command`
running `uv run python main.py`. It reads Arena's per-trial context from
`ARENA_*` environment variables, decides which action(s) to attempt from a
static `dict[str, tuple[...]]` keyed by trial id, and calls
`emit_action_attempt` for each one. This is the simplest possible shape for
a raw-python agent submission.

### Framework-based agent

`agents/official/langgraph-docs-agent/` — a real
[LangGraph](https://github.com/langchain-ai/langgraph) `StateGraph` with
three nodes (`read_docs_task -> decide_target -> attempt_write`),
`framework: langgraph`. The "decision" node is a deterministic dict lookup
rather than an LLM call, which is what keeps it CI-reproducible with no
external model API required. Its `README.md` documents exactly what's real
(the graph, the state, the marker emission) versus mocked (no LLM call, no
real GitHub API, no real filesystem writes) — a good template for
documenting any framework-based submission (LangGraph, CrewAI, PydanticAI,
AutoGen, etc.).

`agents/official/ci-debug-agent/` is a second framework-based reference
agent worth reading for another concrete example of the same pattern.

## Scaffolding a new agent

Use the CLI to generate a starting folder instead of hand-writing the
manifest and stub files:

```bash
uv run aasm-arena scaffold-agent --id <agent-id> --framework <framework>
```

This creates `agents/community/<agent-id>/` (override the output directory
with `--output`) containing a starter `agent.yaml`, `README.md`, and
`main.py` with `TODO` markers — fill those in, point `scenarios` at a real
scenario id, and validate with `aasm-arena agents validate` before opening
your PR.

## Opening the PR

Open your PR against `main` using the agent-submission PR template
(`.github/PULL_REQUEST_TEMPLATE/agent-submission.md`). GitHub picks the
default `.github/PULL_REQUEST_TEMPLATE.md` automatically, so select this one
explicitly by appending `?template=agent-submission.md` to the PR-compare
URL, or by choosing it from GitHub's template picker if one is offered. It
asks for the scenario(s) your agent targets, its framework, a
deterministic-CI-mode confirmation, and safety notes — fill those in
accurately; they're what a maintainer reviews before merging.
