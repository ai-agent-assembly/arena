"""Integrations with agent-assembly and third-party agent frameworks.

`arena.integrations.models` defines `ArenaActionAttempt`, the common event
model every agent framework's attempted action gets normalized into
(AAASM-4379). `arena.integrations.emit` is the emit-side helper agent
scripts call to report an attempt; `arena.integrations.parser` recovers
`ArenaActionAttempt`s from an agent's captured stdout. The agent-assembly
adapter and decision/audit capture that consume these land in AAASM-4378/
AAASM-4380.
"""
