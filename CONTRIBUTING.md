# Contributing to Arena

Arena is a public repo and welcomes outside contributions — new agent plugins, new scenarios/trials, and improvements to the runner and reporting pipeline. This document frames the contribution model at a high level. The detailed submission templates (GitHub Issue Forms for proposing an agent or scenario, manifest validation, PR checklist specifics) are tracked as a separate ticket (AAASM-4392) and are **coming soon** — this section will be filled in with the real templates and validation steps once that work lands.

## How contributions flow

1. **Propose** via a GitHub Issue Form (once published) — for a new agent plugin, a new scenario/trial, or a change to the runner/report pipeline.
2. **Submit** a PR against `main` containing the manifest, plugin code, or scenario/trial definition, following the repo's PR template (`.github/PULL_REQUEST_TEMPLATE.md`) and the commit/branch conventions described in the repo's own contributor docs.
3. **Automated validation** runs via GitHub Actions to check that manifests and scenario/trial definitions are well-formed before a match is attempted.
4. **Review and merge** — approved agents and scenarios become part of Arena's match rotation; official, scheduled matches and their reports are published from `main`.

## Security: untrusted code and secrets

Submitted agent plugins are, by definition, untrusted code from the public. **Untrusted PR code is never run with repository secrets or elevated CI credentials.** Match execution happens inside the runner's sandboxed execution boundary (Docker or an isolated process, depending on the agent's declared execution profile), which has no access to Arena's own repo/CI secrets regardless of what the submitted agent's code attempts to do. Any contribution or workflow change that would give untrusted PR code access to secrets is out of scope and will not be accepted — see `docs/architecture.md` for where this boundary sits in the pipeline.

## What to read first

- [`README.md`](README.md) — what Arena is and isn't.
- [`docs/architecture.md`](docs/architecture.md) — how a match flows from manifest to report, and where agent-assembly's governance boundary sits.
- [`docs/glossary.md`](docs/glossary.md) — precise definitions for the terms used above (Agent, Manifest, Scenario, Trial, Match, Decision, Report, and so on).

Detailed submission mechanics (Issue Form fields, manifest schema, scenario/trial authoring guide) are coming soon.
