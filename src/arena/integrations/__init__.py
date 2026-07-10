"""Integrations with agent-assembly and third-party agent frameworks.

`arena.integrations.models` defines `ArenaActionAttempt`, the common event
model every agent framework's attempted action gets normalized into
(AAASM-4379). `arena.integrations.emit` is the emit-side helper agent
scripts call to report an attempt; `arena.integrations.parser` recovers
`ArenaActionAttempt`s from an agent's captured stdout.
`arena.integrations.adapter` (AAASM-4378) is the seam through which Arena
asks agent-assembly for a `DefenseDecision` on one attempt, and
`arena.integrations.audit` (AAASM-4380) persists the resulting decision (or
missing-decision failure) as an `ArenaAuditEvent` to an append-only JSONL
log. `arena.runner.match.run_match` wires all of these together for a live
match run.
"""
