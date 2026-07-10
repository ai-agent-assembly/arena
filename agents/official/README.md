# Official agents

Agent-assembly-maintained agent submissions, one directory per agent id:

```
agents/official/<agent-id>/agent.yaml
```

Each `agent.yaml` is an `AgentManifest` (see `src/arena/models/manifest.py`).
Discovered and validated by `arena.registry.discovery.discover_agents`,
listable via `aasm-arena agents list`.
