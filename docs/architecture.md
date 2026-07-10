# Architecture

This document explains how Arena is put together at a conceptual level: what each layer is responsible for, and — most importantly — where the line sits between "Arena orchestrates" and "agent-assembly governs." Nothing here describes finalized schemas, CLI flags, or file formats; those land with their own tickets. This is the shape of the system, not its API.

## The core split: orchestration vs. governance

Arena and agent-assembly have deliberately non-overlapping jobs:

- **Arena orchestrates.** It knows how to load an agent plugin, hand it a scenario, run the resulting trials, collect what happened, and write a report. It has no opinion about whether any individual agent action was acceptable.
- **agent-assembly governs.** Every time a submitted agent attempts an action that matters (writing a file, calling a tool, hitting the network, publishing a release, running a shell command), agent-assembly is the system that decides allow, deny, approve (hold for human sign-off), quarantine, or redact. Arena never makes this call itself and never duplicates agent-assembly's policy logic — it calls into agent-assembly (or observes agent-assembly's own audit/decision events) and records whatever agent-assembly decided.

This split is why Arena can stay lightweight: it doesn't need its own policy engine, its own audit trail format for enforcement decisions, or its own notion of "dangerous action." It borrows all of that from agent-assembly and focuses purely on running matches and reporting outcomes.

## The pipeline: manifest → scenario/trial → runner → report

A match moves through four conceptual stages:

1. **Manifest.** Each participating agent is described by a manifest — a declarative description of how to build/run the agent, which framework it's built on, and which scenarios it's eligible to enter. The manifest is the plug-in contract: Arena never imports or hard-codes agent-specific logic, it only reads manifests and invokes what they point to.
2. **Scenario / Trial.** A scenario is a themed setting (for example, `github-maintainer-dungeon`, where the agent plays a GitHub maintainer bot). A scenario is made up of one or more trials — individual, scored situations within that setting, such as a happy-path issue triage, a prompt-injection attempt aimed at getting the agent to write to source, a secret-leak attempt, a release-publish action that should require approval, or a destructive shell command that should be dropped or quarantined. Trials are the unit of pass/fail scoring; a scenario aggregates trial outcomes into a match result.
3. **Runner.** The runner is what actually executes a match: it builds/starts the agent per its manifest inside a sandboxed execution boundary (a container or an isolated process, depending on what the agent needs), feeds it the scenario's trials, and observes both the agent's attempted actions and agent-assembly's resulting decisions. The sandbox boundary matters most for community-submitted agents — submitted plugin code runs without access to repository secrets or elevated credentials, regardless of what the agent's own code tries to do.
4. **Report.** Every match produces a report describing what was attempted, what agent-assembly decided for each attempt, and whether the match counts as a win (agent-assembly held the line: no critical escapes, no unexpected allows, no secret exposures, no bypassed approvals, malicious attempts handled as expected, complete audit data) or a loss (any critical expected deny/drop/redact/ask was instead allowed, or a dangerous action is missing audit evidence). Reports are published in multiple formats — human-readable Markdown, structured JSON, and event-level JSONL — so they can be read directly, consumed by tooling, or replayed for analysis.

## Where sandboxing sits

Because Arena runs agent plugin code that may be submitted by the public, the runner's sandbox boundary (Docker or an isolated process, depending on the execution profile a manifest declares) is a hard requirement, not an optimization. It sits directly around step 3 above: nothing before the runner (parsing a manifest, resolving a scenario) executes agent-submitted code, and nothing the runner starts gets access to Arena's own CI or repository secrets. This is also why automated validation and matches run through GitHub Actions in a way that keeps untrusted PR code out of any privileged context — see `CONTRIBUTING.md` for the contributor-facing version of this rule.

## What Arena deliberately does not own

- Policy definitions for what's allowed or denied — that's agent-assembly's policy engine.
- Enforcement of any individual decision — Arena observes and records, it does not enforce.
- Agent runtimes or planning loops — agents bring their own framework (LangGraph, CrewAI, PydanticAI, AutoGen, plain Python, etc.); Arena only needs a manifest-described way to invoke them.
