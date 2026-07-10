# Official agents

Agent-assembly-maintained agent submissions, one directory per agent id:

```
agents/official/<agent-id>/agent.yaml
```

Each `agent.yaml` is an `AgentManifest` (see `src/arena/models/manifest.py`).
Discovered and validated by `arena.registry.discovery.discover_agents`,
listable via `aasm-arena agents list`.

## What these agents are (and aren't)

These are demonstration contestants for the `github-maintainer-dungeon`
scenario — reference implementations that prove Arena can run agents from
different frameworks (raw Python, LangGraph, PydanticAI) and that
agent-assembly's governance applies to all of them uniformly. Each one is
deliberately "naive": it implements no real governance logic of its own and
exits `0` unconditionally, including for trials where its attempted action
should be denied — enforcing boundaries is agent-assembly's job, not
theirs (see each agent's own README for its specific framework/mocking
notes). None of these are production recommendations for how to build an
agent; they exist solely to be governed, not to be copied into a real
deployment.
