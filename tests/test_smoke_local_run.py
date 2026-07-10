"""AAASM-4376 smoke test: `aasm-arena run` completes end to end for a
developer following `docs/local-execution.md`, with no external services,
secrets, or live Docker daemon required.

Deliberately uses a **dedicated, self-contained fixture** (a tiny no-op
scenario + a tiny no-op agent, both written under `tmp_path`) rather than
the real `github-maintainer-dungeon` scenario / `raw-python-issue-triager`
official agent that `tests/test_cli_run.py` already exercises. Two reasons:

1. Speed/isolation — one trial instead of five keeps this genuinely a
   *smoke* test, not a full scenario run.
2. Portability — the real official agent's `entrypoint.command` resolves
   its own `main.py` via a `../../../../`-relative offset back to the repo
   root (see the comment in `agents/official/raw-python-issue-triager/
   agent.yaml` and `docs/local-execution.md`), which only works when the
   trial workspace is nested under the repo root at a fixed depth — not
   true for an isolated `tmp_path`-based `--output-root`, which is the
   correct, hermetic way for a test to invoke `aasm-arena run` (see the
   docstring on `test_run_github_maintainer_dungeon_smoke_with_official_agent`
   in `tests/test_cli_run.py` for the full explanation of that limitation).
   This fixture's agent command instead uses `sys.executable` plus an
   absolute path to its own script, so it resolves correctly regardless of
   where its trial workspace ends up.
"""

from __future__ import annotations

import shlex
import sys
from pathlib import Path

from typer.testing import CliRunner

from arena.cli import app

runner = CliRunner()

_NOOP_AGENT_SCRIPT = '''\
"""No-op smoke-test agent: acknowledges the trial context and exits 0."""
import os

trial_id = os.environ.get("ARENA_TRIAL_ID", "<unknown-trial>")
print(f"smoke-agent handled trial {trial_id!r}")
'''


def _write_noop_scenario(scenarios_root: Path, scenario_id: str = "smoke-scenario") -> None:
    scenario_dir = scenarios_root / scenario_id
    trials_dir = scenario_dir / "trials"
    trials_dir.mkdir(parents=True)
    (scenario_dir / "scenario.yaml").write_text(
        f"id: {scenario_id}\n"
        "name: Smoke Test Scenario\n"
        "description: A single-trial no-op scenario used only by the AAASM-4376 smoke test.\n"
        "trials:\n"
        "  - noop-trial\n"
    )
    (trials_dir / "noop-trial.yaml").write_text(
        "id: noop-trial\n"
        "description: A benign no-op trial with nothing to triage.\n"
        "expected:\n"
        "  some.action: allow\n"
        "severity: low\n"
    )


def _write_noop_agent(official_root: Path, agent_id: str = "smoke-noop-agent") -> None:
    agent_dir = official_root / agent_id
    agent_dir.mkdir(parents=True)
    script_path = agent_dir / "main.py"
    script_path.write_text(_NOOP_AGENT_SCRIPT)

    command = f"{shlex.quote(sys.executable)} {shlex.quote(str(script_path))}"
    (agent_dir / "agent.yaml").write_text(
        f"id: {agent_id}\n"
        "name: Smoke Noop Agent\n"
        "framework: raw-python\n"
        "entrypoint:\n"
        "  type: command\n"
        f'  command: "{command}"\n'
        "runtime:\n"
        "  type: process\n"
        "scenarios:\n"
        "  - smoke-scenario\n"
    )


def test_local_run_smoke_completes_end_to_end(tmp_path: Path) -> None:
    """The AAASM-4376 AC: a developer can run a local match skeleton — no
    external services, secrets, or Docker daemon required — and it
    completes without crashing, producing a real on-disk workspace.
    """
    scenarios_root = tmp_path / "scenarios"
    official_root = tmp_path / "agents" / "official"
    community_root = tmp_path / "agents" / "community"
    output_root = tmp_path / "runs"
    _write_noop_scenario(scenarios_root)
    _write_noop_agent(official_root)

    result = runner.invoke(
        app,
        [
            "run",
            "smoke-scenario",
            "--scenarios-root",
            str(scenarios_root),
            "--official-root",
            str(official_root),
            "--community-root",
            str(community_root),
            "--output-root",
            str(output_root),
        ],
    )

    assert result.exit_code == 0, result.stdout
    assert "match complete" in result.stdout

    match_dirs = list(output_root.iterdir())
    assert len(match_dirs) == 1
    trial_workspace = match_dirs[0] / "smoke-noop-agent" / "noop-trial"
    assert trial_workspace.is_dir()
