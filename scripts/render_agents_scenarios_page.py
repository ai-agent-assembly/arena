#!/usr/bin/env python3
"""Render `docs/agents-scenarios.md` from the live agent manifests and
scenario specs on disk (AAASM-4521).

Nothing in the docs nav previously surfaced `agents/official/*/agent.yaml`
(and `agents/community/*/agent.yaml`) or `scenarios/*/scenario.yaml` as a
browsable catalog — a reader had no quick way to see what agents Arena can
field or what scenarios/capabilities are under test without reading raw
YAML in the repo. This script closes that gap the same way AAASM-4429/4506's
`scripts/render_latest_reports_page.py` closed the equivalent gap for match
reports: generate the page from the real source data at build time rather
than hand-authoring it, because community submissions add new agents (see
`agents/community/README.md`, AAASM-4393/4394/4395's PR path) and nobody
would reliably remember to hand-update a static catalog page on every new
submission.

Reuses `arena.registry.discovery.discover_agents` and
`arena.scenarios.loader.load_scenario_registry` — the same manifest/scenario
loading code the CLI and runner use — rather than re-parsing YAML by hand,
so this page can never drift from what Arena itself considers a valid,
loadable agent or scenario.

Not part of the installed `arena` package — a repo-local build step, run
before `mkdocs build`/`mkdocs serve` so the page reflects whatever is
currently on disk under `agents/`/`scenarios/`:

    uv run python scripts/render_agents_scenarios_page.py
    uv run mkdocs build --strict

`.github/workflows/documentation.yml` runs it before every build (PR-check
and deploy alike), so the generated page's *content* is always regenerated
fresh from whatever is on disk at build time — no new commit required per
refresh. The output file (`docs/agents-scenarios.md`) is nonetheless
committed/tracked (not gitignored), matching `docs/latest-reports.md`'s
precedent: the `git-authors` and `git-revision-date-localized` MkDocs
plugins need existing git history for the path to pass `mkdocs build
--strict`, so the tracked file is a snapshot/starting point, not the source
of truth for the page's content.
"""

from __future__ import annotations

from pathlib import Path

from arena.models.manifest import AgentManifest
from arena.registry.discovery import AgentRegistry, AgentSource, discover_agents
from arena.scenarios.loader import ScenarioBundle, load_scenario_registry

REPO_ROOT = Path(__file__).resolve().parent.parent
OFFICIAL_AGENTS_ROOT = REPO_ROOT / "agents" / "official"
COMMUNITY_AGENTS_ROOT = REPO_ROOT / "agents" / "community"
SCENARIOS_ROOT = REPO_ROOT / "scenarios"
OUTPUT_PATH = REPO_ROOT / "docs" / "agents-scenarios.md"

_SOURCE_LABEL = {
    AgentSource.OFFICIAL: "Official",
    AgentSource.COMMUNITY: "Community",
}


def _render_agents_table(registry: AgentRegistry) -> list[str]:
    lines = [
        "| Agent | Framework | Source | Capabilities |",
        "|---|---|---|---|",
    ]
    for registered in sorted(registry.agents, key=lambda a: a.manifest.id):
        manifest = registered.manifest
        capabilities = ", ".join(f"`{cap}`" for cap in manifest.capabilities) or "_none declared_"
        lines.append(
            f"| **{manifest.name}** (`{manifest.id}`) | {manifest.framework.value} "
            f"| {_SOURCE_LABEL[registered.source]} | {capabilities} |"
        )
    return lines


def _render_agent_behaviors(manifest: AgentManifest) -> list[str]:
    if not manifest.behaviors:
        return []
    lines = [f"### {manifest.name} (`{manifest.id}`) behaviors", ""]
    for behavior in manifest.behaviors:
        lines.append(f"- `{behavior.id}` — {behavior.description}")
    lines.append("")
    return lines


def _render_agents_section(registry: AgentRegistry) -> list[str]:
    lines = ["## Agents", ""]
    lines.extend(_render_agents_table(registry))
    lines.append("")
    for registered in sorted(registry.agents, key=lambda a: a.manifest.id):
        lines.extend(_render_agent_behaviors(registered.manifest))
    return lines


def _render_scenarios_table(scenarios: dict[str, ScenarioBundle]) -> list[str]:
    lines = [
        "| Scenario | Trials | Victory conditions |",
        "|---|---:|---|",
    ]
    for bundle in sorted(scenarios.values(), key=lambda b: b.scenario.id):
        scenario = bundle.scenario
        vc = scenario.victory_conditions
        conditions = (
            f"critical_escapes={vc.critical_escapes}, "
            f"unexpected_allows={vc.unexpected_allows}, "
            f"secret_exposures={vc.secret_exposures}"
        )
        lines.append(
            f"| **{scenario.name}** (`{scenario.id}`) | {len(scenario.trials)} | {conditions} |"
        )
    return lines


def _render_scenario_detail(bundle: ScenarioBundle) -> list[str]:
    scenario = bundle.scenario
    lines = [f"### {scenario.name} (`{scenario.id}`)", "", scenario.description, ""]
    lines.append("**Trials:**")
    lines.append("")
    for trial_id in scenario.trials:
        lines.append(f"- `{trial_id}`")
    lines.append("")
    return lines


def _render_scenarios_section(scenarios: dict[str, ScenarioBundle]) -> list[str]:
    lines = ["## Scenarios", ""]
    lines.extend(_render_scenarios_table(scenarios))
    lines.append("")
    for bundle in sorted(scenarios.values(), key=lambda b: b.scenario.id):
        lines.extend(_render_scenario_detail(bundle))
    return lines


def _render_page(registry: AgentRegistry, scenarios: dict[str, ScenarioBundle]) -> str:
    lines = [
        "# Agents & Scenarios",
        "",
        "The roster of agents Arena can field, and the scenarios/capabilities "
        "currently under test — generated from the live manifests under "
        "`agents/official/`, `agents/community/`, and `scenarios/` (see "
        "`scripts/render_agents_scenarios_page.py`), so this page can't drift "
        "from what's actually loadable.",
        "",
    ]
    lines.extend(_render_agents_section(registry))
    lines.extend(_render_scenarios_section(scenarios))
    return "\n".join(lines).rstrip() + "\n"


def main() -> None:
    registry = discover_agents(OFFICIAL_AGENTS_ROOT, COMMUNITY_AGENTS_ROOT)
    scenarios = load_scenario_registry(SCENARIOS_ROOT)
    OUTPUT_PATH.write_text(_render_page(registry, scenarios), encoding="utf-8")
    print(f"wrote {OUTPUT_PATH} ({len(registry)} agent(s), {len(scenarios)} scenario(s))")


if __name__ == "__main__":
    main()
