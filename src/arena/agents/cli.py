"""`aasm-arena agents` subcommand group: agent plugin manifest validation."""

from __future__ import annotations

from pathlib import Path

import typer
from pydantic import ValidationError
from rich.console import Console
from rich.markup import escape

from arena.agents.loader import ManifestLoadError, load_manifest

agents_app = typer.Typer(
    name="agents",
    help="Inspect and validate agent plugin manifests (agent.yaml).",
    no_args_is_help=True,
)

console = Console()


@agents_app.command("validate")
def validate(
    manifest_path: Path = typer.Argument(
        ...,
        exists=True,
        file_okay=True,
        dir_okay=False,
        readable=True,
        help="Path to an agent.yaml manifest file.",
    ),
) -> None:
    """Validate an agent plugin manifest against the AgentManifest schema."""
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

    console.print(
        f"[bold green]✓[/bold green] {escape(str(manifest_path))} is a valid manifest "
        f"({escape(manifest.id)})"
    )
