# Security Policy

## Reporting a vulnerability

This repository does not carry its own `SECURITY.md` — it inherits the AI Agent Assembly org's default security policy from [`ai-agent-assembly/.github`](https://github.com/ai-agent-assembly/.github/blob/master/SECURITY.md), which GitHub surfaces automatically for any repo (including this one) that doesn't define its own.

If you discover a security vulnerability in Arena or any AI Agent Assembly repository, report it **privately** by emailing **security@agent-assembly.dev**. Do not open a public GitHub issue or discussion for security issues.

The org policy's response process: acknowledgement within 72 hours, an initial assessment within 7 days, coordinated disclosure once a fix is ready, and credit in the release notes for the fixed version (unless you'd rather stay anonymous). For non-security bugs, use the regular [issue tracker](https://github.com/ai-agent-assembly/arena/issues) instead.

## What's in scope

- A real sandbox escape — code in `agents/community/**` or `agents/official/**` gaining access to repository secrets, elevated CI credentials, or the host running Arena's own CI, beyond what its declared `entrypoint`/`runtime` sandbox boundary should allow.
- A `DockerRunner` or `ProcessRunner` misconfiguration that grants a container/process more privilege than its manifest declares (e.g. `--privileged`, host environment passthrough beyond `entrypoint.env`) — see [Runners](runners.md).
- A community-manifest-validation CI workflow (`.github/workflows/validate-community-agents.yml`) that can be tricked into executing untrusted agent code rather than only parsing/schema-checking it.
- Secret or credential leakage through Arena's own report/audit pipeline (`reports/`, `audit.jsonl`) that isn't covered by the redaction guarantee described in [Report schema](report-schema.md).

## What's out of scope

Arena's whole purpose is to run **adversarial, deliberately hostile agent behavior** and record what agent-assembly does about it — so a lot of things that would be alarming in another project are expected, by design, here:

- **Community-submitted agent manifests declaring hostile intent.** An agent whose `agent.yaml`/`main.py` declares an attempt to read secrets, push directly to `main`, or run a destructive shell command is not a vulnerability report — it's exactly what Arena's `github-maintainer-dungeon` scenario and its trials exist to test. See [Submitting an agent](submit-agent.md)'s "Deterministic-mode expectation": every such attempt must be a *declared* marker via `arena.integrations.emit.emit_action_attempt`, never a real action, and is reviewed for that property before merge.
- **Community agent submissions execute in a sandboxed, no-secrets CI context** (AAASM-4395). The manifest-validation workflow that runs on every PR touching `agents/community/**` only parses and schema-checks `agent.yaml` — it never invokes the agent's declared `entrypoint`. A full match (which does execute the agent, inside its sandbox) only runs after merge to `main` or explicit maintainer trigger, never automatically against unreviewed fork-PR code. Untrusted PR code never has access to repository secrets or elevated CI credentials at any point in this flow — see `CONTRIBUTING.md`'s "Security: untrusted code and secrets" section and [Architecture → Where sandboxing sits](architecture.md#where-sandboxing-sits).
- **A trial scoring as a "defeat."** If a match run shows a critical escape (agent-assembly failed to hold the line — see [Escape (Critical Escape)](glossary.md) in the Glossary), that's Arena's reporting pipeline working as intended, not a bug in Arena itself. A defeat is expected to route a follow-up issue back to the core `agent-assembly` repo, since that's where the actual governance gap lives.
