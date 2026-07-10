## Description

Brief description of the agent plugin this PR submits.

## Agent Details

- Agent id (`agents/community/<agent-id>/`): 
- Framework (`raw-python` / `langgraph` / `crewai` / `pydantic-ai` / `autogen` / `other`): 
- Scenario(s) this agent targets: 

## Type of Change

- [ ] ✨ New community agent submission
- [ ] ♻️ Update to an existing community agent

## Deterministic CI Mode

- [ ] I confirm this agent behaves deterministically for the scenarios it targets — no live network calls, no calls to a real LLM/model API, no real destructive actions. See `docs/submit-agent.md` for what "deterministic" means here.

## Safety Notes

Describe what this agent's `main.py` actually does for each trial it targets (or link to the manifest's `capabilities` list). Confirm none of the following are present:

- [ ] No real secrets, credentials, or tokens anywhere in the submission
- [ ] No code that executes a real shell command, deletes a real file, or makes a real network/API call
- [ ] Any "attack" or adversarial behavior is declared via `arena.integrations.emit.emit_action_attempt` markers only, never actually executed (see `agents/official/mock-malicious-agent/main.py` for the reference pattern)

## Manifest Validation

- [ ] `uv run aasm-arena agents validate agents/community/<agent-id>/agent.yaml` passes locally
- [ ] `agent.yaml` declares only capabilities the agent actually attempts

## Breaking Changes

Does this PR introduce any breaking changes to manifest/scenario/report schemas or the CLI?

- [ ] No
- [ ] Yes (describe below)

## Related Issues

- Jira ticket: [AAASM-XX](https://lightning-dust-mite.atlassian.net/browse/AAASM-XX)
- Related GitHub issues: #XX

## Testing

Describe the testing performed for this PR:

- [ ] `uv run aasm-arena agents validate ...` passes
- [ ] Manual local run performed (`uv run aasm-arena run <scenario> --agent <agent-id>`)
- [ ] No tests required (explain why)

## Checklist

- [ ] Code follows project style guidelines (`ruff check`, `ruff format`, `mypy`)
- [ ] Self-review of the diff completed
- [ ] `docs/submit-agent.md` folder structure and manifest requirements followed
- [ ] All CI checks passing
- [ ] Commits are small and follow the Gitmoji convention

## Maintainer Notes

Submitted agent code is not executed with repository secrets or elevated CI credentials. Automated CI on this PR performs static/schema validation only (see `docs/architecture.md`); a maintainer will run this agent through a full match — in a sandboxed runner, after merge or explicit maintainer approval — before it appears in Arena's regular match rotation.
