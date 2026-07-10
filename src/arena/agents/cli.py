"""`aasm-arena agents` subcommand group: agent plugin manifest validation."""

from __future__ import annotations

from pathlib import Path

import typer
from pydantic import ValidationError
from rich.console import Console
from rich.markup import escape
from rich.table import Table

from arena.agents.loader import ManifestLoadError, load_manifest
from arena.models.manifest import AgentFramework
from arena.registry.discovery import AgentSource, RegistryLoadError, discover_agents

agents_app = typer.Typer(
    name="agents",
    help="Inspect and validate agent plugin manifests (agent.yaml).",
    no_args_is_help=True,
)

console = Console()


@agents_app.command("validate")
def validate(
    path: Path = typer.Argument(
        ...,
        exists=True,
        file_okay=True,
        dir_okay=True,
        readable=True,
        help="Path to an agent.yaml manifest file, or a directory containing "
        "one subdirectory per agent (each with its own agent.yaml).",
    ),
) -> None:
    """Validate agent plugin manifest(s) against the AgentManifest schema.

    Given a single `agent.yaml` file, validates just that manifest. Given a
    directory (e.g. `agents/community`), validates every `<agent-id>/agent.yaml`
    found directly under it and additionally checks that each manifest's `id`
    matches its directory name. This is schema/folder-structure validation
    only — it never executes anything an agent's `entrypoint` points to, so
    it's safe to run in CI against untrusted submissions.
    """
    if path.is_dir():
        _validate_directory(path)
        return
    _validate_manifest_file(path)


def _validate_manifest_file(manifest_path: Path) -> None:
    try:
        manifest = load_manifest(manifest_path)
    except ManifestLoadError as exc:
        console.print(f"[bold red]✗[/bold red] {escape(str(exc))}")
        raise typer.Exit(code=1) from exc
    except ValidationError as exc:
        console.print(f"[bold red]✗ manifest is invalid:[/bold red] {escape(str(manifest_path))}")
        for error in exc.errors():
            field = ".".join(str(part) for part in error["loc"]) or "<root>"
            console.print(f"  [red]•[/red] [bold]{escape(field)}[/bold]: {escape(error['msg'])}")
        raise typer.Exit(code=1) from exc

    behaviors = ", ".join(behavior.id for behavior in manifest.behaviors) or "none"
    console.print(
        f"[bold green]✓[/bold green] {escape(str(manifest_path))} is a valid manifest "
        f"({escape(manifest.id)}) — behaviors: {escape(behaviors)}"
    )


def _validate_directory(root: Path) -> None:
    agent_dirs = sorted(p for p in root.iterdir() if p.is_dir())

    if not agent_dirs:
        console.print(f"[yellow]No agent submissions found under {escape(str(root))}[/yellow]")
        return

    had_error = False
    for agent_dir in agent_dirs:
        manifest_path = agent_dir / "agent.yaml"
        if not manifest_path.is_file():
            console.print(
                f"[bold red]✗[/bold red] {escape(agent_dir.name)}: missing required "
                f"{escape(str(manifest_path))}"
            )
            had_error = True
            continue

        try:
            manifest = load_manifest(manifest_path)
        except ManifestLoadError as exc:
            console.print(f"[bold red]✗[/bold red] {escape(agent_dir.name)}: {escape(str(exc))}")
            had_error = True
            continue
        except ValidationError as exc:
            console.print(
                f"[bold red]✗ {escape(agent_dir.name)} manifest is invalid:[/bold red] "
                f"{escape(str(manifest_path))}"
            )
            for error in exc.errors():
                field = ".".join(str(part) for part in error["loc"]) or "<root>"
                msg = escape(error["msg"])
                console.print(f"  [red]•[/red] [bold]{escape(field)}[/bold]: {msg}")
            had_error = True
            continue

        if manifest.id != agent_dir.name:
            console.print(
                f"[bold red]✗[/bold red] {escape(agent_dir.name)}: manifest id "
                f"{escape(manifest.id)!r} does not match directory name "
                f"{escape(agent_dir.name)!r}"
            )
            had_error = True
            continue

        console.print(f"[bold green]✓[/bold green] {escape(agent_dir.name)} is a valid manifest")

    if had_error:
        raise typer.Exit(code=1)


@agents_app.command("list")
def list_agents(
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
    framework: AgentFramework | None = typer.Option(
        None,
        "--framework",
        case_sensitive=False,
        help="Only show agents built on this framework.",
    ),
    scenario: str | None = typer.Option(
        None,
        "--scenario",
        help="Only show agents eligible for this scenario id.",
    ),
    source: AgentSource | None = typer.Option(
        None,
        "--source",
        case_sensitive=False,
        help="Only show agents from this source ('official' or 'community').",
    ),
) -> None:
    """List agent manifests discovered under the official/community registry roots."""
    try:
        registry = discover_agents(official_root, community_root)
    except RegistryLoadError as exc:
        console.print(f"[bold red]✗[/bold red] {escape(str(exc))}")
        raise typer.Exit(code=1) from exc

    agents = registry.filter(framework=framework, scenario=scenario, source=source)

    if not agents:
        console.print("[yellow]No agents found.[/yellow]")
        return

    table = Table(title="Arena Agent Registry")
    table.add_column("ID")
    table.add_column("Name")
    table.add_column("Framework")
    table.add_column("Source")
    table.add_column("Scenarios")
    table.add_column("Behaviors")

    for agent in sorted(agents, key=lambda a: a.manifest.id):
        table.add_row(
            escape(agent.manifest.id),
            escape(agent.manifest.name),
            escape(agent.manifest.framework.value),
            escape(agent.source.value),
            escape(", ".join(agent.manifest.scenarios)),
            escape(", ".join(behavior.id for behavior in agent.manifest.behaviors) or "—"),
        )

    console.print(table)
