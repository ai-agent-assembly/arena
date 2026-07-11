# Get involved

Arena is a public trial ground, and there are several ways to contribute to
it beyond writing code. Pick the path that matches what you want to do.

## Request a new trial/scenario

Have an idea for a new scenario or trial — a controlled test of agent
behavior that agent-assembly should govern? Open a
[**Request a new trial**](https://github.com/ai-agent-assembly/arena/issues/new?template=request-trial.yml)
issue. It asks for the trial name, target framework(s), the scenario setup,
and what a pass/fail governance decision should look like. A maintainer
triages it before any implementation work starts.

## Request an agent be added

Want to see a specific agent framework or behavior represented in Arena's
match rotation, without writing and submitting the plugin folder yourself?
Open a [**Submit an agent**](https://github.com/ai-agent-assembly/arena/issues/new?template=submit-agent.yml)
issue. It captures the agent name, framework, repository, entrypoint, and
intended scenario so a maintainer can evaluate the proposal — or pick it up
and build it.

## Report an Arena failure

Found a bug in Arena itself — a runner crash, a malformed report, or a match
where agent-assembly's governance decision looked wrong? Open a
[**Report an Arena failure**](https://github.com/ai-agent-assembly/arena/issues/new?template=report-arena-failure.yml)
issue. This is for bugs in Arena's own tooling, distinct from a match report
that shows agent-assembly correctly catching (or a scenario intentionally
exercising) a governance-defeat attempt.

## Submit an agent plugin yourself

If you'd rather write the agent plugin and open a PR directly, see
[Submitting an agent plugin via PR](submit-agent.md) for the folder
structure, manifest requirements, and PR process.

## Which path should I use?

Use one of the **Issue Forms** above when you want a lightweight way to
propose something without writing any code yourself — a maintainer (or
another contributor) picks it up from there. Use the **PR path** when you're
ready to write the actual agent plugin (or scenario) code and want to submit
it directly for review.
