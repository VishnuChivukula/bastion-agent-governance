"""`bastion evidence`: write the pack for one agent to disk."""

import asyncio
import sys
import tempfile
from pathlib import Path

import typer
from sqlalchemy import Engine

from bastion.config import REPO_ROOT, Settings, get_settings
from bastion.db import make_engine
from bastion.evidence.generator import UnknownAgent, generate
from bastion.evidence.pdf import PdfUnavailable, html_to_pdf


def _write(engine: Engine, agent_id: str, out: Path) -> tuple[Path, Path | None, int]:
    try:
        pack, html = generate(engine, agent_id, actor="cli")
    except UnknownAgent as exc:
        typer.echo(f"Unknown agent '{agent_id}'. Run `make serve` or `make demo` first.", err=True)
        raise typer.Exit(code=1) from exc
    out.mkdir(parents=True, exist_ok=True)
    html_path = out / f"evidence-pack-{agent_id}.html"
    html_path.write_text(html, encoding="utf-8")
    try:
        pdf = html_to_pdf(html, document_name=pack.document_name, footer_note=pack.disclaimer)
    except PdfUnavailable as exc:
        typer.echo(f"PDF skipped: {exc}", err=True)
        return html_path, None, 0
    pdf_path = out / f"evidence-pack-{agent_id}.pdf"
    pdf_path.write_bytes(pdf)
    return html_path, pdf_path, pdf.count(b"/Type /Page") - pdf.count(b"/Type /Pages")


async def _demo_then_write(agent_id: str, out: Path, settings: Settings):
    if str(REPO_ROOT) not in sys.path:  # the `bastion` script does not have the repo on its path
        sys.path.insert(0, str(REPO_ROOT))
    from demo.loan_ops_agent.run import DemoEnvironment
    from demo.loan_ops_agent.scenarios import SCENARIOS

    with (
        tempfile.TemporaryDirectory(prefix="bastion-evidence-") as tmp,
        DemoEnvironment(Path(tmp), settings) as env,
    ):
        await env.runner.warm_up()
        for scenario in SCENARIOS:
            env.reset_between_scenarios()
            await env.runner.run_scripted(scenario)
        return await asyncio.to_thread(_write, env.engine, agent_id, out)


def write_pack(agent_id: str, out: Path, *, demo: bool = False, settings: Settings | None = None):
    """Returns (html path, pdf path or None, page count)."""
    settings = settings or get_settings()
    if demo:
        replay = settings.model_copy(update={"mode": "replay"})
        return asyncio.run(_demo_then_write(agent_id, out, replay))
    engine = make_engine(settings.db_path)
    try:
        if settings.seed_on_start:
            from bastion.api.state import _seed

            _seed(engine, settings)
        return _write(engine, agent_id, out)
    finally:
        engine.dispose()
