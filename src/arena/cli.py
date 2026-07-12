"""Arena CLI entrypoint.

This is mostly still a skeleton entrypoint. It does not implement match
running or reporting — those land in later tickets (AAASM-4364 and onward).
It exists so the `aasm-arena` console script has somewhere real to point,
plus (AAASM-4369) a `scenarios validate` command for scenario/trial YAML.
"""

from __future__ import annotations

import re
from pathlib import Path

import typer
from rich.console import Console
from rich.markup import escape
from rich.table import Table

from arena.agents.cli import agents_app
from arena.integrations.adapter import AdapterChoice, build_agent_assembly_client
from arena.integrations.audit import read_audit_events
from arena.models.manifest import AGENT_ID_PATTERN, AgentFramework
from arena.reports.generate import build_execution_metadata, generate_report
from arena.reports.github_issues import GitHubIssueCreationError, create_issues_for_report
from arena.reports.index import refresh_static_index
from arena.reports.issue_payload import build_issue_payloads_for_report
from arena.reports.models import MatchReport
from arena.reports.scoring import score_match
from arena.runner.llm_mode import LLMMode
from arena.runner.match import AUDIT_LOG_FILENAME, MatchConfig, MatchOrchestrationError, run_match
from arena.scenarios.loader import ScenarioLoadError, load_scenario, load_scenario_registry

app = typer.Typer(
    name="aasm-arena",
    help="Governance trial arena for AI agents — agents attempt actions, "
    "agent-assembly governs, every match leaves a report.",
    no_args_is_help=True,
)

app.add_typer(agents_app, name="agents")

scenarios_app = typer.Typer(
    name="scenarios",
    help="Validate scenario/trial YAML definitions.",
    no_args_is_help=True,
)
app.add_typer(scenarios_app, name="scenarios")

reports_app = typer.Typer(
    name="reports",
    help="Inspect generated match reports.",
    no_args_is_help=True,
)
app.add_typer(reports_app, name="reports")

console = Console()

__version__ = "0.0.0"


@app.command()
def version() -> None:
    """Print the arena CLI version."""
    console.print(f"aasm-arena {__version__}")


@app.command()
def hello() -> None:
    """Print a friendly greeting to confirm the CLI is wired up."""
    console.print("Hello from arena.")


@app.command("run")
def run_command(
    scenario_id: str = typer.Argument(
        ..., help="Scenario id to run, e.g. 'github-maintainer-dungeon'."
    ),
    agent: str | None = typer.Option(
        None,
        "--agent",
        help="Run only this agent id instead of every agent compatible with the scenario.",
    ),
    scenarios_root: Path = typer.Option(
        Path("scenarios"),
        "--scenarios-root",
        help="Root directory containing scenario folders.",
    ),
    official_root: Path = typer.Option(
        Path("agents/official"),
        "--official-root",
        help="Root directory containing official agent submissions.",
    ),
    community_root: Path = typer.Option(
        Path("agents/community"),
        "--community-root",
        help="Root directory containing community agent submissions.",
    ),
    output_root: Path = typer.Option(
        Path("runs"),
        "--output-root",
        help="Root directory under which each match's report workspace is created.",
    ),
    reports_root: Path = typer.Option(
        Path("reports/matches"),
        "--reports-root",
        help="Root directory under which the durable arena-report.md/arena-report.json/"
        "audit.jsonl artifacts are written, as <reports-root>/<match-id>/.",
    ),
    adapter: str = typer.Option(
        "fake",
        "--adapter",
        help="Which agent-assembly adapter to use: 'fake' (default, deterministic "
        "backend) or 'real' (not yet implemented — out of scope for AAASM-4377).",
    ),
    llm_mode: str = typer.Option(
        "mock",
        "--llm-mode",
        help="Which LLM execution mode agents run under (AAASM-4405): 'mock' "
        "(default, zero paid model API calls), 'replay' (also zero paid model "
        "API calls — replays previously recorded model responses), or 'live' "
        "(real, paid model API calls; requires AASM_ARENA_LIVE_LLM=true to be "
        "set explicitly, and is never set by this repo's own CI workflows).",
    ),
) -> None:
    """Run a match: select compatible agents, run every scenario trial, print a summary.

    Exits non-zero when `MatchScore.victory` is `False` (AAASM-4389's
    `arena.reports.scoring.score_match` — see below). Execution is real:
    `ProcessRunner` (AAASM-4374) actually launches `command`-type agents as
    subprocesses, and `DockerRunner` (AAASM-4375) actually launches
    `docker`-type agents in containers. Scoring is real too (AAASM-4380):
    every attempted action is decided by the configured
    `AgentAssemblyClient` and `TrialOutcome.passed` is a real comparison
    against the trial's `expected` mapping, not a proxy — see the module
    docstring in `arena.runner.match` for exactly what "passed" means, and
    `docs/local-execution.md` for what's still mocked (only the adapter
    itself, via `AdapterChoice.FAKE`).

    `--adapter` selects which `AgentAssemblyClient` (AAASM-4378,
    `arena.integrations.adapter`) the run uses to decide every attempted
    action; it's validated and stored on `MatchConfig.adapter`, then
    consumed by `run_match` for every trial.

    `--llm-mode` selects which LLM execution mode (AAASM-4405,
    `arena.runner.llm_mode`) the run's agents operate under; it's validated
    and stored on `MatchConfig.llm_mode`, then enforced by `run_match` before
    anything else runs — `'live'` is rejected unless `AASM_ARENA_LIVE_LLM=true`
    is set, which keeps it out of ordinary and PR/fork CI runs by
    construction (see `docs/local-execution.md`'s "LLM execution mode
    policy" section).

    The final verdict comes from `score_match(result, result.scenario,
    read_audit_events(...))` rather than comparing
    `result.critical_escapes` against its threshold inline — `score_match`
    is the single source of truth for how every failure-mode count maps to
    `agent-assembly wins`/`agent-assembly loses`, so this command reads
    that verdict instead of re-deriving a narrower (critical-escapes-only)
    one of its own.

    After scoring, `arena.reports.generate.generate_report` (AAASM-4390)
    writes the match's durable report artifacts — `arena-report.md`,
    `arena-report.json`, `audit.jsonl` — under `<reports_root>/<match-id>/`
    (default `reports/matches/`, distinct from `--output-root`'s ad-hoc
    per-trial scratch workspace tree), and this command prints the report
    directory path. `arena.reports.index.refresh_static_index` (AAASM-4397)
    then rebuilds `<reports_root's parent>/latest.json`, `latest.md`, and
    `leaderboard.json` from every match report on disk, so a website/docs
    consumer always has an up-to-date static index after each run.
    """
    try:
        adapter_choice = AdapterChoice(adapter)
    except ValueError:
        valid = ", ".join(choice.value for choice in AdapterChoice)
        console.print(
            f"[bold red]✗[/bold red] invalid --adapter {escape(adapter)!r}: "
            f"must be one of {escape(valid)}"
        )
        raise typer.Exit(code=1) from None

    try:
        build_agent_assembly_client(adapter_choice)
    except NotImplementedError as exc:
        console.print(f"[bold red]✗[/bold red] {escape(str(exc))}")
        raise typer.Exit(code=1) from exc

    try:
        llm_mode_choice = LLMMode(llm_mode)
    except ValueError:
        valid = ", ".join(choice.value for choice in LLMMode)
        console.print(
            f"[bold red]✗[/bold red] invalid --llm-mode {escape(llm_mode)!r}: "
            f"must be one of {escape(valid)}"
        )
        raise typer.Exit(code=1) from None

    config = MatchConfig(
        scenarios_root=scenarios_root,
        official_root=official_root,
        community_root=community_root,
        output_root=output_root,
        reports_root=reports_root,
        adapter=adapter_choice,
        llm_mode=llm_mode_choice,
    )
    try:
        result = run_match(scenario_id, config, agent_id=agent)
    except MatchOrchestrationError as exc:
        console.print(f"[bold red]✗[/bold red] {escape(str(exc))}")
        raise typer.Exit(code=1) from exc

    console.print(f"[bold]Match[/bold] {escape(result.match_id)} — scenario {escape(scenario_id)}")
    console.print(f"Workspace: {escape(str(result.workspace))}")

    table = Table(title="Trial Outcomes")
    table.add_column("Agent")
    table.add_column("Trial")
    table.add_column("Severity")
    table.add_column("Exit Code")
    table.add_column("Result")

    for outcome in result.trial_outcomes:
        status = "[green]PASS[/green]" if outcome.passed else "[red]FAIL[/red]"
        table.add_row(
            escape(outcome.agent_id),
            escape(outcome.trial.id),
            escape(outcome.trial.severity.value),
            str(outcome.result.exit_code),
            status,
        )
    console.print(table)

    execution_metadata = build_execution_metadata(result)
    console.print(
        f"LLM mode: {escape(execution_metadata.llm_mode.value)} "
        f"(deterministic={execution_metadata.deterministic}, "
        f"external_model_calls={execution_metadata.external_model_calls}, "
        f"estimated_cost_usd={execution_metadata.estimated_cost_usd})"
    )
    if not execution_metadata.deterministic:
        console.print(
            "[bold yellow]⚠ live LLM mode — this report is NOT deterministic[/bold yellow]"
        )

    audit_events = read_audit_events(result.workspace / AUDIT_LOG_FILENAME)
    score = score_match(result, result.scenario, audit_events)
    victory_conditions = result.scenario.victory_conditions

    console.print(
        f"Critical escapes: {score.critical_escapes} "
        f"(threshold {victory_conditions.critical_escapes})"
    )
    console.print(
        f"Unexpected allows: {score.unexpected_allows} "
        f"(threshold {victory_conditions.unexpected_allows})"
    )
    console.print(
        f"Secret exposures: {score.secret_exposures} "
        f"(threshold {victory_conditions.secret_exposures})"
    )
    console.print(f"Approval bypasses: {score.approval_bypasses}")
    console.print(f"Missing audits: {score.missing_audits}")
    console.print(f"Agent runtime failures: {score.agent_runtime_failures}")
    console.print(f"Result: {escape(score.outcome.value)}")

    report_dir = generate_report(result, score, audit_events, reports_root=reports_root)
    console.print(f"Report: {escape(str(report_dir))}")

    refresh_static_index(reports_root)
    console.print(f"Static index: {escape(str(reports_root.parent))}")

    if not score.victory:
        console.print("[bold red]✗ victory conditions violated[/bold red]")
        raise typer.Exit(code=1)

    console.print("[bold green]✓ match complete[/bold green]")


TEMPLATE_DIR = Path(__file__).resolve().parents[2] / "templates" / "agent-plugin"


@app.command("scaffold-agent")
def scaffold_agent(
    id: str = typer.Option(
        ..., "--id", help="Agent id (lowercase kebab-case, e.g. 'my-cool-agent')."
    ),
    framework: str = typer.Option(
        ...,
        "--framework",
        help="Agent framework. One of: " + ", ".join(f.value for f in AgentFramework),
    ),
    output: Path = typer.Option(
        Path("agents/community"),
        "--output",
        help="Directory under which the new '<id>/' scaffold folder is created.",
    ),
) -> None:
    """Scaffold a new agent plugin: agent.yaml, README.md, and an entrypoint stub."""
    if not re.fullmatch(AGENT_ID_PATTERN, id):
        console.print(
            f"[bold red]✗[/bold red] invalid --id {escape(id)!r}: "
            f"must match pattern {escape(AGENT_ID_PATTERN)}"
        )
        raise typer.Exit(code=1)

    try:
        framework_enum = AgentFramework(framework)
    except ValueError:
        valid = ", ".join(f.value for f in AgentFramework)
        console.print(
            f"[bold red]✗[/bold red] invalid --framework {escape(framework)!r}: "
            f"must be one of {escape(valid)}"
        )
        raise typer.Exit(code=1) from None

    target_dir = output / id
    if target_dir.exists():
        console.print(
            f"[bold red]✗[/bold red] target directory already exists: {escape(str(target_dir))}"
        )
        raise typer.Exit(code=1)

    replacements = {
        "__AGENT_ID__": id,
        "__AGENT_NAME__": id.replace("-", " ").title(),
        "__FRAMEWORK__": framework_enum.value,
        "__SCENARIO_ID__": "REPLACE-WITH-SCENARIO-ID",
    }

    target_dir.mkdir(parents=True)
    for template_name, output_name in (
        ("agent.yaml.tmpl", "agent.yaml"),
        ("README.md.tmpl", "README.md"),
        ("main.py.tmpl", "main.py"),
    ):
        rendered = (TEMPLATE_DIR / template_name).read_text()
        for token, value in replacements.items():
            rendered = rendered.replace(token, value)
        (target_dir / output_name).write_text(rendered)

    console.print(
        f"[bold green]✓[/bold green] scaffolded agent {escape(id)} at {escape(str(target_dir))}"
    )


@scenarios_app.command("validate")
def scenarios_validate(
    path: Path = typer.Argument(
        ...,
        exists=True,
        file_okay=False,
        dir_okay=True,
        help="A single scenario folder (containing scenario.yaml), or a "
        "registry root containing multiple scenario folders.",
    ),
) -> None:
    """Validate a scenario folder, or every scenario folder under a registry root."""
    try:
        if (path / "scenario.yaml").is_file():
            bundle = load_scenario(path)
            console.print(
                f"[green]OK[/green] {bundle.scenario.id} ({len(bundle.trials)} trial(s) validated)"
            )
            return

        registry = load_scenario_registry(path)
        if not registry:
            console.print(f"[yellow]No scenario folders found under {path}[/yellow]")
            return
        for scenario_id, bundle in registry.items():
            console.print(
                f"[green]OK[/green] {scenario_id} ({len(bundle.trials)} trial(s) validated)"
            )
    except ScenarioLoadError as exc:
        console.print(f"[red]FAILED[/red] {exc}")
        raise typer.Exit(code=1) from exc


@reports_app.command("defeat-issues")
def reports_defeat_issues(
    report_path: Path = typer.Argument(
        ...,
        exists=True,
        file_okay=True,
        dir_okay=False,
        help="Path to an arena-report.json file "
        "(e.g. reports/matches/<match-id>/arena-report.json).",
    ),
    dry_run: bool = typer.Option(
        True,
        "--dry-run/--no-dry-run",
        help="Print the GitHub issue payload(s) without filing anything (default). "
        "--no-dry-run actually files each payload as a real GitHub issue via the `gh` "
        "CLI (AAASM-4505, `arena.reports.github_issues`), skipping any defeat that "
        "already has a matching open issue. Requires GH_TOKEN or GITHUB_TOKEN in the "
        "environment — see reports/README.md for the required ARENA_DEFEAT_ISSUE_TOKEN "
        "secret this is sourced from in CI.",
    ),
) -> None:
    """Print — or, with `--no-dry-run`, actually file — the GitHub issue(s)
    `report_path`'s defeats would produce, one per defeat signal
    (`arena.reports.defeat.classify_defeats` -> `route_defeat` ->
    `arena.reports.issue_payload.build_issue_payload`).

    The default `--dry-run` path never calls the GitHub API — see
    `arena.reports.issue_payload`'s module docstring for why. `--no-dry-run` hands
    every payload to `arena.reports.github_issues.create_issues_for_report`, which
    does call the GitHub API (via `gh`) and is the only path in this command that
    does. Prints nothing but a confirmation message for a winning report's empty
    defeat list, either way, and never even checks for a token in that case.
    """
    report = MatchReport.model_validate_json(report_path.read_text(encoding="utf-8"))
    payloads = build_issue_payloads_for_report(report)

    if not payloads:
        console.print("[green]No defeats found — no issues to file.[/green]")
        return

    if dry_run:
        for index, payload in enumerate(payloads):
            if index:
                console.print("---")
            console.print(f"[bold]repo:[/bold] {escape(payload.repo)}")
            console.print(f"[bold]title:[/bold] {escape(payload.title)}")
            console.print(f"[bold]labels:[/bold] {escape(', '.join(payload.labels))}")
            console.print(f"[bold]fingerprint:[/bold] {escape(payload.fingerprint)}")
            console.print(escape(payload.body))
        return

    try:
        results = create_issues_for_report(payloads)
    except GitHubIssueCreationError as exc:
        console.print(f"[bold red]✗[/bold red] {escape(str(exc))}")
        raise typer.Exit(code=1) from exc

    for result in results:
        if result.skipped_duplicate:
            console.print(
                f"[yellow]⚠ skipped (duplicate of {escape(result.issue_url)})[/yellow] "
                f"{escape(result.payload.repo)}: {escape(result.payload.title)}"
            )
        else:
            console.print(
                f"[bold green]✓ created {escape(result.issue_url)}[/bold green] "
                f"{escape(result.payload.repo)}: {escape(result.payload.title)}"
            )


if __name__ == "__main__":
    app()
