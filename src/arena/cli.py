"""Arena CLI entrypoint.

This is a skeleton entrypoint only. It does not implement match running,
scenario loading, or reporting — those land in later tickets
(AAASM-4364 and onward). It exists so the `aasm-arena` console script has
somewhere real to point and so `--help` and a trivial command can be
smoke-tested end to end.
"""

from __future__ import annotations

import typer
from rich.console import Console

app = typer.Typer(
    name="aasm-arena",
    help="Governance trial arena for AI agents — agents attempt actions, "
    "agent-assembly governs, every match leaves a report.",
    no_args_is_help=True,
)

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


if __name__ == "__main__":
    app()
