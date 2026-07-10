# Arena

**Arena is a public, plug-in based trial ground for demonstrating [agent-assembly](https://github.com/ai-agent-assembly/agent-assembly) governance — it is not another agent framework, and it does not reimplement agent-assembly's governance logic.**

AI agents from different frameworks (LangGraph, CrewAI, PydanticAI, AutoGen, raw Python, and others) enter controlled scenarios in Arena and attempt normal work alongside deliberate boundary violations — prompt injection, secret leaks, destructive shell commands, unapproved releases. `agent-assembly` is the sole governance defender: it makes every allow/deny/approve/quarantine decision. Arena only orchestrates the match, runs the scenario, records what happened, and publishes the report.

> Agents enter. agent-assembly defends. Every match leaves a report.

## What Arena is (and isn't)

- Arena **is** an orchestrator: it loads agent plugins via manifest, runs them through scenario/trial definitions, and captures the resulting decisions and outcomes into a report.
- Arena **is not** a new agent framework. It does not provide agent runtimes, planning loops, or tool-calling abstractions — agents bring their own framework of choice and plug in.
- Arena **is not** a governance engine. It never makes an allow/deny/approve/quarantine call itself. Every enforcement decision comes from `agent-assembly`; Arena treats those decisions as the source of truth and records them.
- Arena vs. [`examples`](https://github.com/ai-agent-assembly/examples): `examples` shows how to *integrate* agent-assembly into your own agent code — small, framework-specific snippets you copy into a real project. Arena is a *competitive proving ground* — full scenarios where independently submitted agents are scored on whether agent-assembly successfully constrained them, including deliberate attack attempts. If you want "how do I wire this up," read `examples`. If you want "does this actually hold up under attack," look at Arena's match reports.

## The thesis

Agents can be powerful, unpredictable, or even intentionally adversarial. The value agent-assembly provides isn't that agents can do work — it's that their actions can be bounded, audited, approved, dropped, or quarantined regardless of what the agent itself decides to attempt. Arena exists to make that value observable: every match is a public, repeatable demonstration of agent-assembly holding the line (or, when it doesn't, a public record of exactly where it failed).

See [`docs/architecture.md`](docs/architecture.md) for how a match actually flows from agent plugin to published report, and [`docs/glossary.md`](docs/glossary.md) for precise definitions of the terms used throughout.

## Quickstart

The project skeleton (uv-managed Python package, CLI entrypoint, manifest/scenario schemas) is landing in parallel tickets and isn't part of this branch. Once it's in place, the intended flow is:

```bash
git clone https://github.com/ai-agent-assembly/arena.git
cd arena
uv sync
uv run aasm-arena --help
```

`aasm-arena` is the intended CLI entrypoint for running scenarios and inspecting reports locally. Exact subcommands and flags will be documented as they land — this section will be filled in with real usage once the runner ships.

## Sample reports

Every match produces `arena-report.md` and `arena-report.json` (plus a raw `audit.jsonl`) under `reports/matches/<match-id>/`. Two deterministic samples, built from the real `github-maintainer-dungeon` scenario, are checked in under [`docs/samples/`](docs/samples/) so you can see the actual shape of a report without running a match yourself:

- [`docs/samples/winning-match/`](docs/samples/winning-match/) ([Markdown](docs/samples/winning-match/arena-report.md) · [JSON](docs/samples/winning-match/arena-report.json)) — every trial resolves exactly as expected: `agent-assembly wins`, zero critical escapes, zero unexpected allows, zero secret exposures.
- [`docs/samples/losing-match/`](docs/samples/losing-match/) ([Markdown](docs/samples/losing-match/arena-report.md) · [JSON](docs/samples/losing-match/arena-report.json)) — the `prompt-injection-code-write` trial's direct-push attempt is unexpectedly allowed instead of denied: `agent-assembly loses`, with exactly one critical escape.

These are regenerated with `uv run python scripts/generate_report_samples.py` and asserted against by `tests/test_reports_snapshots.py` — see that module's docstring for the determinism strategy behind them.

## Submitting an agent

At a high level, adding an agent to Arena means submitting a **manifest** — a YAML file describing how to build/run your agent, which framework it uses, and which scenarios it's eligible for — plus whatever plugin code the manifest points to. Submissions go through a public GitHub Issue Form and a PR, the same as any other contribution.

Untrusted, community-submitted agent code is never run with repository secrets or elevated CI credentials — it runs inside the sandboxed match runner (Docker or an isolated process boundary) with no access to Arena's own CI/repo secrets.

The detailed manifest schema, submission template, and validation flow are tracked in later tickets (starting with the manifest schema ticket) and aren't final yet — this README will link to them once they exist.

## CI

Every pull request and push to `main` runs [`.github/workflows/ci.yml`](.github/workflows/ci.yml):
`ruff check`, `ruff format --check`, `mypy src`, `pytest`, and an import smoke check
across every `arena` subpackage (a stand-in "schema smoke check" until the
Pydantic manifest/scenario/report schemas land). No secrets are required.

## Contributing

See [`CONTRIBUTING.md`](CONTRIBUTING.md) for the contribution framing, and [`docs/architecture.md`](docs/architecture.md) / [`docs/glossary.md`](docs/glossary.md) for the concepts referenced throughout this repo.

## License

MIT — see [`LICENSE`](LICENSE).
