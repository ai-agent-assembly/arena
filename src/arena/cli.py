"""Arena CLI entrypoint.

This is mostly still a skeleton entrypoint. It does not implement match
running or reporting — those land in later tickets (AAASM-4364 and onward).
It exists so the `aasm-arena` console script has somewhere real to point,
plus (AAASM-4369) a `scenarios validate` command for scenario/trial YAML.
"""

from __future__ import annotations

from pathlib import Path

import typer
from rich.console import Console

from arena.agents.cli import agents_app
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


if __name__ == "__main__":
    app()
