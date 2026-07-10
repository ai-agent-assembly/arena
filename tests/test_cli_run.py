"""CLI tests for `aasm-arena run`, including the AAASM-4373 smoke test:
running an official agent through the real `github-maintainer-dungeon`
scenario end to end.
"""

from __future__ import annotations

from pathlib import Path

from typer.testing import CliRunner

from arena.cli import app

runner = CliRunner()

REPO_ROOT = Path(__file__).resolve().parent.parent
REAL_SCENARIOS_ROOT = REPO_ROOT / "scenarios"
REAL_OFFICIAL_ROOT = REPO_ROOT / "agents" / "official"
REAL_COMMUNITY_ROOT = REPO_ROOT / "agents" / "community"


def _write_scenario(root: Path, scenario_id: str = "test-scenario") -> None:
    scenario_dir = root / scenario_id
    trials_dir = scenario_dir / "trials"
    trials_dir.mkdir(parents=True)
    (scenario_dir / "scenario.yaml").write_text(
        f"id: {scenario_id}\n"
        f"name: Test Scenario\n"
        f"description: Scenario used for aasm-arena run CLI tests.\n"
        f"trials:\n"
        f"  - happy-trial\n"
    )
    (trials_dir / "happy-trial.yaml").write_text(
        "id: happy-trial\n"
        "description: A benign trial.\n"
        "expected:\n"
        "  some.action: allow\n"
        "severity: low\n"
    )


def _write_agent(root: Path, agent_id: str, scenario_ids: list[str]) -> None:
    agent_dir = root / agent_id
    agent_dir.mkdir(parents=True)
    scenarios_yaml = "\n".join(f"  - {sid}" for sid in scenario_ids)
    (agent_dir / "agent.yaml").write_text(
        f"id: {agent_id}\n"
        f"name: {agent_id.title()}\n"
        f"framework: raw-python\n"
        f'entrypoint:\n  type: command\n  command: "python main.py"\n'
        f"runtime:\n  type: process\n"
        f"scenarios:\n{scenarios_yaml}\n"
    )


def test_run_smoke_scenario_succeeds(tmp_path: Path) -> None:
    scenarios_root = tmp_path / "scenarios"
    official_root = tmp_path / "agents" / "official"
    community_root = tmp_path / "agents" / "community"
    _write_scenario(scenarios_root)
    _write_agent(official_root, "smoke-agent", ["test-scenario"])

    result = runner.invoke(
        app,
        [
            "run",
            "test-scenario",
            "--scenarios-root",
            str(scenarios_root),
            "--official-root",
            str(official_root),
            "--community-root",
            str(community_root),
            "--output-root",
            str(tmp_path / "runs"),
        ],
    )

    assert result.exit_code == 0, result.stdout
    assert "smoke-agent" in result.stdout
    assert "match complete" in result.stdout


def test_run_unknown_scenario_exits_nonzero(tmp_path: Path) -> None:
    scenarios_root = tmp_path / "scenarios"
    scenarios_root.mkdir()

    result = runner.invoke(
        app,
        [
            "run",
            "does-not-exist",
            "--scenarios-root",
            str(scenarios_root),
            "--official-root",
            str(tmp_path / "agents" / "official"),
            "--community-root",
            str(tmp_path / "agents" / "community"),
            "--output-root",
            str(tmp_path / "runs"),
        ],
    )

    assert result.exit_code != 0
    assert "not found" in " ".join(result.stdout.split())


def test_run_agent_filter_selects_only_that_agent(tmp_path: Path) -> None:
    scenarios_root = tmp_path / "scenarios"
    official_root = tmp_path / "agents" / "official"
    community_root = tmp_path / "agents" / "community"
    _write_scenario(scenarios_root)
    _write_agent(official_root, "agent-a", ["test-scenario"])
    _write_agent(community_root, "agent-b", ["test-scenario"])

    result = runner.invoke(
        app,
        [
            "run",
            "test-scenario",
            "--agent",
            "agent-a",
            "--scenarios-root",
            str(scenarios_root),
            "--official-root",
            str(official_root),
            "--community-root",
            str(community_root),
            "--output-root",
            str(tmp_path / "runs"),
        ],
    )

    assert result.exit_code == 0, result.stdout
    assert "agent-a" in result.stdout
    assert "agent-b" not in result.stdout


def test_run_github_maintainer_dungeon_smoke_with_official_agent(tmp_path: Path) -> None:
    """AAASM-4373 AC: a smoke test can run an official agent through every
    trial without the match itself crashing. Uses the real
    `github-maintainer-dungeon` scenario and the real
    `raw-python-issue-triager` official agent manifest committed to this
    repo, but writes match output under a tmp dir instead of the repo tree.

    AAASM-4374 finding: `raw-python-issue-triager/agent.yaml` declares
    `entrypoint.command: "uv run python main.py"`, but the agent's directory
    (`agents/official/raw-python-issue-triager/`) only contains `agent.yaml`
    — there is no `main.py`. Under `NoOpRunner` this was invisible (nothing
    was actually launched); under the real `ProcessRunner` now wired in for
    `EntrypointType.COMMAND`, every trial genuinely launches `uv run python
    main.py` and genuinely fails (`python: can't open file 'main.py'`,
    non-zero exit) because the script doesn't exist. That's a fixture gap in
    the example official agent, not a `ProcessRunner` bug — see AAASM-4374's
    PR description — so this test is intentionally not "fixed" by adding a
    working `main.py` here; it instead asserts the AC that actually matters
    for this ticket: a failing command entrypoint reports per-trial failures
    and a non-zero match exit code instead of crashing `aasm-arena run`.

    The agent id/trial ids are asserted via the on-disk workspace rather than
    `result.stdout`, since Rich truncates the CLI's summary table to the test
    runner's (narrow, non-tty) terminal width.
    """
    output_root = tmp_path / "runs"
    result = runner.invoke(
        app,
        [
            "run",
            "github-maintainer-dungeon",
            "--agent",
            "raw-python-issue-triager",
            "--scenarios-root",
            str(REAL_SCENARIOS_ROOT),
            "--official-root",
            str(REAL_OFFICIAL_ROOT),
            "--community-root",
            str(REAL_COMMUNITY_ROOT),
            "--output-root",
            str(output_root),
        ],
    )

    # Non-zero: the missing main.py fails every trial, including the
    # scenario's critical-severity ones, which violates victory conditions —
    # see the AAASM-4374 finding above. The command still runs cleanly
    # end-to-end (no crash, no traceback) and reports it via the CLI.
    assert result.exit_code != 0, result.stdout
    assert "victory conditions violated" in result.stdout

    match_dirs = list(output_root.iterdir())
    assert len(match_dirs) == 1
    agent_workspace = match_dirs[0] / "raw-python-issue-triager"
    assert agent_workspace.is_dir()
    assert (agent_workspace / "issue-triage-happy-path").is_dir()
    assert (agent_workspace / "prompt-injection-code-write").is_dir()
    assert (agent_workspace / "secret-leak-attempt").is_dir()
    assert (agent_workspace / "release-publish-requires-approval").is_dir()
    assert (agent_workspace / "destructive-command-drop").is_dir()
