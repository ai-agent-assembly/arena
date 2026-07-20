"""Unit tests for `scripts/render_agents_scenarios_page.py` (AAASM-4521).

`scripts/` isn't part of the installed `arena` package, so the module is
loaded directly from its file path via `importlib` rather than a normal
`import` statement — same pattern as
`tests/test_render_latest_reports_page.py`.

Covers:

- `main()` against this repo's real `agents/official/`, `agents/community/`,
  and `scenarios/` content produces output reflecting the real current data:
  all 5 real official agent names appear, and the real scenario's trials and
  victory conditions appear correctly.
- A synthetic, isolated fixture set (own agents/scenarios roots under
  `tmp_path`) exercises the rendering logic itself — capabilities,
  behaviors, and scenario description/trials/victory-conditions — without
  depending on this repo's real content ever staying exactly as it is today.
"""

from __future__ import annotations

import importlib.util
from pathlib import Path
from types import ModuleType

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
SCRIPT_PATH = REPO_ROOT / "scripts" / "render_agents_scenarios_page.py"


def _load_script_module() -> ModuleType:
    spec = importlib.util.spec_from_file_location("render_agents_scenarios_page", SCRIPT_PATH)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


render = _load_script_module()


# --- against this repo's real agents/ + scenarios/ content --------------------------

#: The 5 official agents' declared `name` fields, as of AAASM-4521 — see
#: each `agents/official/*/agent.yaml`. Asserting on these (rather than just
#: a count) proves the generated page reflects real manifest content, not
#: just "some agents were found".
_REAL_OFFICIAL_AGENT_NAMES = [
    "CI Debug Agent (PydanticAI)",
    "LangGraph Docs Agent",
    "Mock Malicious Agent",
    "Raw Python Issue Triage Agent",
    "Release Agent",
]


def test_main_reflects_real_repo_agents_and_scenario(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    output_path = tmp_path / "agents-scenarios.md"
    monkeypatch.setattr(render, "OUTPUT_PATH", output_path)

    render.main()

    output = output_path.read_text(encoding="utf-8")

    for name in _REAL_OFFICIAL_AGENT_NAMES:
        assert name in output

    # The real scenario, its trials, and its victory conditions.
    assert "GitHub Maintainer Dungeon" in output
    assert "`github-maintainer-dungeon`" in output
    for trial_id in [
        "issue-triage-happy-path",
        "prompt-injection-code-write",
        "secret-leak-attempt",
        "release-publish-requires-approval",
        "destructive-command-drop",
    ]:
        assert f"`{trial_id}`" in output
    assert "critical_escapes=0" in output
    assert "unexpected_allows=0" in output
    assert "secret_exposures=0" in output


# --- against an isolated synthetic fixture set ---------------------------------------


def _write_agent_manifest(
    agents_root: Path, agent_id: str, *, behaviors: bool = True, containerized: bool = False
) -> None:
    behaviors_yaml = (
        """
behaviors:
  - id: normal
    description: Does ordinary, in-lane work.
  - id: secret-seeking
    description: Attempts to read a secret it shouldn't.
"""
        if behaviors
        else ""
    )
    # Community submissions must be containerized (`require_containerized_entrypoint`),
    # so a community fixture declares a docker entrypoint; official agents use command.
    entrypoint_yaml = (
        "entrypoint:\n  type: docker\n  image: fixture:latest\nruntime:\n  type: container"
        if containerized
        else 'entrypoint:\n  type: command\n  command: "true"\nruntime:\n  type: process'
    )
    agent_dir = agents_root / agent_id
    agent_dir.mkdir(parents=True)
    (agent_dir / "agent.yaml").write_text(
        f"""
id: {agent_id}
name: Fixture Agent {agent_id}
framework: raw-python
{entrypoint_yaml}
scenarios:
  - fixture-scenario
capabilities:
  - fixture.read
  - fixture.write
{behaviors_yaml}""",
        encoding="utf-8",
    )


def _write_scenario(scenarios_root: Path) -> None:
    scenario_dir = scenarios_root / "fixture-scenario"
    trials_dir = scenario_dir / "trials"
    trials_dir.mkdir(parents=True)
    (scenario_dir / "scenario.yaml").write_text(
        """
id: fixture-scenario
name: Fixture Scenario
description: A scenario used only for this test.
victory_conditions:
  critical_escapes: 1
  unexpected_allows: 2
  secret_exposures: 3
trials:
  - fixture-trial-one
  - fixture-trial-two
""",
        encoding="utf-8",
    )
    for trial_id in ["fixture-trial-one", "fixture-trial-two"]:
        (trials_dir / f"{trial_id}.yaml").write_text(
            f"""
id: {trial_id}
description: A fixture trial.
expected:
  fixture.read: allow
severity: low
""",
            encoding="utf-8",
        )


def test_main_renders_synthetic_fixture_agents_and_scenario(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    official_root = tmp_path / "agents" / "official"
    community_root = tmp_path / "agents" / "community"
    scenarios_root = tmp_path / "scenarios"
    official_root.mkdir(parents=True)
    community_root.mkdir(parents=True)
    scenarios_root.mkdir(parents=True)

    _write_agent_manifest(official_root, "fixture-official-agent")
    _write_agent_manifest(
        community_root, "fixture-community-agent", behaviors=False, containerized=True
    )
    _write_scenario(scenarios_root)

    output_path = tmp_path / "agents-scenarios.md"
    monkeypatch.setattr(render, "OFFICIAL_AGENTS_ROOT", official_root)
    monkeypatch.setattr(render, "COMMUNITY_AGENTS_ROOT", community_root)
    monkeypatch.setattr(render, "SCENARIOS_ROOT", scenarios_root)
    monkeypatch.setattr(render, "OUTPUT_PATH", output_path)

    render.main()

    output = output_path.read_text(encoding="utf-8")

    assert "Fixture Agent fixture-official-agent" in output
    assert "Official" in output
    assert "Fixture Agent fixture-community-agent" in output
    assert "Community" in output
    assert "`fixture.read`" in output
    assert "`fixture.write`" in output
    assert "`normal` — Does ordinary, in-lane work." in output
    assert "`secret-seeking` — Attempts to read a secret it shouldn't." in output

    assert "Fixture Scenario" in output
    assert "A scenario used only for this test." in output
    assert "`fixture-trial-one`" in output
    assert "`fixture-trial-two`" in output
    assert "critical_escapes=1" in output
    assert "unexpected_allows=2" in output
    assert "secret_exposures=3" in output
