# Behavior Profiles

Behavior profiles (AAASM-4404) let a single agent submission demonstrate multiple, distinct trial-specific behaviors — for example `normal` vs. `prompt-injection-vulnerable` vs. `secret-seeking` — without needing a separate agent folder per behavior. A manifest declares the profiles it supports; a trial optionally targets one of them.

This page documents the schema as it exists today. See the module docstrings in [`src/arena/models/manifest.py`](https://github.com/ai-agent-assembly/arena/blob/main/src/arena/models/manifest.py) and [`src/arena/models/scenario.py`](https://github.com/ai-agent-assembly/arena/blob/main/src/arena/models/scenario.py) for the authoritative source — the rendered reference below is generated directly from that source.

## Status: schema and validation only

AAASM-4404 is **schema/validation only**. Nothing in Arena today reads a trial's `behavior_id` to actually switch what an agent process does at runtime — that's follow-up work (AAASM-4405/4406). Today, `behaviors` and `behavior_id` are validated and can be inspected, but a match run doesn't yet dispatch an agent into a specific behavior at execution time.

## `BehaviorProfile` (`agent.yaml`)

A `BehaviorProfile` is a named behavior mode an agent manifest can declare under its top-level `behaviors` list:

| Field | Type | Required | Notes |
| --- | --- | --- | --- |
| `id` | `str` | yes | Lowercase kebab-case, 2–64 characters — same pattern as an agent id (`^[a-z0-9]+(-[a-z0-9]+)*$`). |
| `description` | `str` | yes | Human-readable description of what this behavior mode does, non-empty. |

`AgentManifest.behaviors` (`list[BehaviorProfile]`, default: empty list):

- Optional — an agent that declares no `behaviors` is a "legacy/simple" agent with no behavior-profile distinction. Every manifest written before AAASM-4404 remains valid unchanged.
- A non-empty `behaviors` list must declare each profile **explicitly** — there is no implicit `normal` entry injected.
- Every `id` in `behaviors` must be unique; a manifest with duplicate behavior ids fails validation with the offending id(s) named in the error.

Example `agent.yaml` excerpt:

```yaml
id: mock-malicious-agent
name: Mock Malicious Agent
framework: raw-python
entrypoint:
  type: command
  command: "uv run python main.py"
runtime:
  type: process
scenarios:
  - github-maintainer-dungeon
behaviors:
  - id: normal
    description: Behaves like a well-intentioned maintainer bot.
  - id: prompt-injection-vulnerable
    description: Follows embedded prompt-injection instructions in issue bodies.
  - id: secret-seeking
    description: Attempts to read and exfiltrate secret-shaped files when possible.
```

## `TrialSpec.behavior_id` (scenario/trial YAML)

A trial may optionally set `behavior_id` to name the `BehaviorProfile` it expects the agent to run under, instead of whichever mode the agent defaults to:

- Optional, defaults to `None` — "no behavior-profile distinction." Every trial written before AAASM-4404, and any scenario that doesn't care about behavior profiles, stays valid unchanged.
- When set, it must be lowercase kebab-case, matching the same id pattern as an agent id.
- Cross-referential validation — that a set `behavior_id` is actually declared by an agent compatible with this trial's scenario — is **not** `TrialSpec`'s job. See `arena.scenarios.loader.validate_trial_behaviors`.

## API reference

::: arena.models.manifest.BehaviorProfile
    options:
      show_root_heading: true
      show_root_toc_entry: false
      show_source: true

::: arena.models.scenario.TrialSpec
    options:
      show_root_heading: true
      show_root_toc_entry: false
      show_source: true
