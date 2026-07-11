# Arena

Arena is the public trial ground for agent-assembly governance. Agents enter, agent-assembly defends, and every match leaves a report.

Arena is an orchestrator, not a governance engine: it loads agent plugins, runs them through scenario/trial definitions, and records the resulting decisions — every allow/deny/approve/quarantine call comes from [agent-assembly](https://github.com/ai-agent-assembly/agent-assembly) itself. It's also not [`examples`](https://github.com/ai-agent-assembly/examples): `examples` is small, framework-specific integration snippets, while Arena runs full cross-framework governance trials — adversarial scenarios, behavior profiles, deterministic mock/replay agents — and publishes match reports.

## Quickstart

```bash
git clone https://github.com/ai-agent-assembly/arena.git
cd arena
uv sync
uv run aasm-arena --help
```

## Docs

Full documentation — architecture, glossary, scenario/manifest authoring, local execution, runners — lives at **[docs.agent-assembly.com/arena](https://docs.agent-assembly.com/arena)**.

Product page: [agent-assembly.com](https://agent-assembly.com)

## Sample reports

Two deterministic sample match reports (a win and a loss) are checked in under [`docs/samples/`](docs/samples/) so you can see the report shape without running a match yourself. Each match also refreshes top-level static index files under `reports/` (`latest.json`/`latest.md`, `leaderboard.json`) so a website or docs site can fetch the latest results directly — see [`reports/README.md`](reports/README.md) for the full layout and schema.

## Contributing

See [`CONTRIBUTING.md`](CONTRIBUTING.md) for how to propose an agent, scenario, or change, and the [PR template](.github/PULL_REQUEST_TEMPLATE.md) for what a submission should include. To propose something without opening a PR yourself, use the [submit an agent](.github/ISSUE_TEMPLATE/submit-agent.yml), [request a trial](.github/ISSUE_TEMPLATE/request-trial.yml), or [report an Arena failure](.github/ISSUE_TEMPLATE/report-arena-failure.yml) issue forms.

## License

MIT — see [`LICENSE`](LICENSE).
