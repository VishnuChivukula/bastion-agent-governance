"""Bastion command-line interface."""

import typer

from bastion.config import get_settings

app = typer.Typer(
    help="Bastion: runtime governance control plane for AI agents.", no_args_is_help=True
)


@app.callback()
def main() -> None:
    """Reference implementation; not production; not legal advice."""


@app.command()
def preflight() -> None:
    """Report mode and whether an API key is configured. Never prints the key."""
    settings = get_settings()
    typer.echo(f"mode: {settings.mode}")
    typer.echo("KEY_SET" if settings.has_api_key else "KEY_MISSING")
