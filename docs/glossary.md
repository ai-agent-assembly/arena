# Glossary

Definitions for terms used throughout Arena's docs, reports, and (eventually) its manifest/scenario schemas. These are conceptual definitions — none of them imply a finalized schema or API; exact field names and formats land with their own tickets.

**Arena**
The project itself: a public, plug-in based trial ground that orchestrates matches between submitted AI agents and agent-assembly's governance layer. Arena is not another agent framework and does not reimplement agent-assembly's governance logic.

**Agent (Agent Plugin)**
A submitted AI agent, built on any framework (LangGraph, CrewAI, PydanticAI, AutoGen, raw Python, etc.), that plugs into Arena via a manifest. Arena runs it against scenarios without needing to know anything about its internals beyond what the manifest declares. Also referred to as "Agent Plugin" in ticket/planning language.

**Manifest**
The declarative description of an agent plugin — how to build/run it, which framework it uses, and which scenarios it's eligible for. The manifest is the contract between a submitted agent and the Arena runner; Arena reads manifests rather than hard-coding agent-specific logic.

**Scenario**
A themed setting an agent is dropped into for a match — for example `github-maintainer-dungeon`, where the agent plays a GitHub maintainer bot. A scenario is composed of one or more trials.

**Trial**
A single, individually scored situation within a scenario — e.g. a happy-path issue triage, a prompt-injection attempt aimed at source-code write, a secret-leak attempt, a release-publish action requiring approval, or a destructive shell command that should be dropped/quarantined. Trials are the unit of pass/fail scoring that roll up into a match result.

**Match**
One full run of an agent through a scenario's trials, producing a single report. A match is won or lost as a whole, based on the aggregate outcome of its trials.

**Attack Attempt**
A trial (or an agent action within a trial) that is deliberately adversarial — prompt injection, secret exfiltration, destructive commands, unapproved releases, etc. — designed to test whether agent-assembly's governance holds under intentional boundary-pushing, not just accidental misuse.

**Runner**
The Arena component that executes a match: it starts the agent per its manifest inside a sandboxed execution boundary (Docker or an isolated process), drives it through the scenario's trials, and observes the agent's attempted actions alongside agent-assembly's decisions about them.

**Decision (Defense Decision)**
The governance verdict agent-assembly renders for a given agent action: **allow**, **deny**, **approve** (held for human sign-off), **quarantine**, or **redact**. Decisions always come from agent-assembly — Arena only records them, it never makes this call itself.

**Escape (Critical Escape)**
A case where an action that should have been denied, dropped, redacted, or held for approval was instead allowed through. A critical escape is the headline failure mode Arena's reports are built to surface — its presence is a primary reason a match is scored as a loss.

**Victory**
The outcome of a match in which agent-assembly successfully held the line: zero critical escapes, zero unexpected allows, zero secret exposures, no bypassed required approvals, malicious/attack-attempt trials handled as expected (dropped or quarantined), and complete audit/report data for every action.

**Defeat**
The outcome of a match in which agent-assembly failed to hold the line: any critical expected deny/drop/redact/ask was instead allowed, or a dangerous action is missing audit evidence. A defeat is expected to route a follow-up issue back to the core `agent-assembly` repo (this routing is delivered in a later ticket).

**Report (Arena Report)**
The published output of a match: what was attempted, what agent-assembly decided for each attempt, and whether the match was a victory or a defeat. Reports are published in three formats — human-readable Markdown, structured JSON, and event-level JSONL — so they can be read directly, consumed by tooling, or replayed.

**Official Agent vs. Community Agent**
An **official agent** is one of Arena's own cross-framework reference agents, maintained as part of the project to give every scenario a baseline of known-good and known-malicious behavior. A **community agent** is one submitted by an outside contributor via the public submission flow. Both run under the same sandboxing rules — community submissions never receive repository secrets or elevated CI credentials.
