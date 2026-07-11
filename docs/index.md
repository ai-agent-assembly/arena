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

To actually run a match against the bundled `github-maintainer-dungeon` scenario, see [Running Arena locally](local-execution.md) — it covers prerequisites, the full command set, where output lands, and troubleshooting.

## Where to go next

| If you want to… | Go to |
| --- | --- |
| Understand how a match flows from manifest to report | [Architecture](architecture.md) |
| Look up precise terms (Agent, Manifest, Scenario, Trial, Decision, …) | [Glossary](glossary.md) |
| See how one agent can be tested under multiple named modes | [Behavior Profiles](behavior-profiles.md) |
| Run a match on your machine | [Running Arena locally](local-execution.md) |
| Understand `ProcessRunner` vs. `DockerRunner` and when each applies | [Runners](runners.md) |
| Submit an agent plugin via PR | [Submitting an agent](submit-agent.md) |
| Understand the static report artifact layout (`reports/latest.json`, `leaderboard.json`, …) | [Report schema](report-schema.md) |
| See a real win/loss report end to end | [Reports → Sample reports](report-schema.md#sample-reports) |
| Report a security vulnerability | [Security Policy](security-policy.md) |
| Look up a Pydantic model's exact fields | [API Reference](api-reference.md) |

## Sample reports

Two deterministic sample match reports (a win and a loss) are published as part of this site so you can see the report shape without running a match yourself — see [Reports → Sample reports](report-schema.md#sample-reports).

## Contributing

See [`CONTRIBUTING.md`](https://github.com/ai-agent-assembly/arena/blob/main/CONTRIBUTING.md) for how to propose an agent, scenario, or change, and [Submitting an agent](submit-agent.md) for the PR-based agent submission path.

## License

MIT — see [`LICENSE`](https://github.com/ai-agent-assembly/arena/blob/main/LICENSE).
