"""Scenario definitions describing what a match asks agents to attempt.

The YAML loader/validator (AAASM-4369) lives in `arena.scenarios.loader`.
Concrete scenario content (e.g. `github-maintainer-dungeon`) lands in
AAASM-4370.

`arena.scenarios.fixtures` (AAASM-4371) is a small loader for the static
local test fixtures under `tests/fixtures/github_maintainer_dungeon/`,
added ahead of the rest of this package's logic because AAASM-4370 needs
it to wire fixtures into scenario/trial specs.
"""
