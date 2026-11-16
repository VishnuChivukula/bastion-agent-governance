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


@app.command("verify-audit")
def verify_audit() -> None:
    """Verify the audit hash chain. Exit code 1 if it is broken (FR-31)."""
    from bastion.audit.verify import verify_chain
    from bastion.db import make_engine

    result = verify_chain(make_engine(get_settings().db_path))
    if result.ok:
        typer.echo(f"OK: {result.events} events, chain intact (head {result.head_hash[:16]}…)")
        return
    typer.echo(f"BROKEN at seq {result.first_broken_seq}: {result.reason}", err=True)
    raise typer.Exit(code=1)
