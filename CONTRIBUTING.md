# Contributing to Arena

Arena is a public repo and welcomes outside contributions — new agent plugins, new scenarios/trials, and improvements to the runner and reporting pipeline. This document frames the contribution model at a high level.

For the PR-based path — submitting an agent plugin directly as a pull request — see [`docs/submit-agent.md`](docs/submit-agent.md) for the required folder structure, manifest requirements, deterministic-mode expectations, and worked examples, and use the `.github/PULL_REQUEST_TEMPLATE/agent-submission.md` PR template. The Issue-Forms-only request path (proposing an agent or scenario without submitting the plugin code yourself) is tracked as a separate ticket (AAASM-4393) and is **coming soon**.

## How contributions flow

1. **Propose** via a GitHub Issue Form (once published) — for a new agent plugin, a new scenario/trial, or a change to the runner/report pipeline. Or, for an agent plugin, skip straight to submitting a PR — see [`docs/submit-agent.md`](docs/submit-agent.md).
2. **Submit** a PR against `main` containing the manifest, plugin code, or scenario/trial definition, following the repo's PR template (`.github/PULL_REQUEST_TEMPLATE.md`, or `.github/PULL_REQUEST_TEMPLATE/agent-submission.md` for agent plugin submissions) and the commit/branch conventions described in the repo's own contributor docs.
3. **Automated validation** runs via GitHub Actions to check that manifests and scenario/trial definitions are well-formed before a match is attempted.
4. **Review and merge** — approved agents and scenarios become part of Arena's match rotation; official, scheduled matches and their reports are published from `main`.

## Security: untrusted code and secrets

Submitted agent plugins are, by definition, untrusted code from the public. **Untrusted PR code is never run with repository secrets or elevated CI credentials.** Match execution happens inside the runner's sandboxed execution boundary (Docker or an isolated process, depending on the agent's declared execution profile), which has no access to Arena's own repo/CI secrets regardless of what the submitted agent's code attempts to do. Any contribution or workflow change that would give untrusted PR code access to secrets is out of scope and will not be accepted — see `docs/architecture.md` for where this boundary sits in the pipeline.

## What to read first

- [`README.md`](README.md) — what Arena is and isn't.
- [`docs/architecture.md`](docs/architecture.md) — how a match flows from manifest to report, and where agent-assembly's governance boundary sits.
- [`docs/glossary.md`](docs/glossary.md) — precise definitions for the terms used above (Agent, Manifest, Scenario, Trial, Match, Decision, Report, and so on).
- [`docs/submit-agent.md`](docs/submit-agent.md) — the PR-based agent submission guide: folder structure, manifest requirements, deterministic-mode expectations, security review notes, and worked examples.

Detailed Issue Form submission mechanics (for the propose-only path) and the scenario/trial authoring guide are coming soon.
