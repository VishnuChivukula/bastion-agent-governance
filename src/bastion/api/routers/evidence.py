"""Evidence pack (FR-50, UC-09): JSON, HTML preview and PDF download for one agent."""

import threading
import time
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import HTMLResponse, Response

from bastion.api.auth import Actor, State
from bastion.api.state import AppState
from bastion.evidence.generator import EvidencePack, UnknownAgent, generate
from bastion.evidence.pdf import PdfUnavailable, html_to_pdf

router = APIRouter(tags=["evidence"])

# Rendering is read-only but not free (the PDF starts a headless browser), and these routes
# are open on a public demo. One render at a time, and a short cache per agent.
_TTL_S = 30.0
_lock = threading.Lock()
_cache: dict[tuple[int, str], tuple[float, EvidencePack, str, bytes | None]] = {}


def _pack(
    state: AppState, agent_id: str, who: str, *, pdf: bool
) -> tuple[EvidencePack, str, bytes]:
    key = (id(state.engine), agent_id)
    with _lock:
        hit = _cache.get(key)
        if hit is None or time.monotonic() - hit[0] > _TTL_S:
            try:
                pack, html = generate(state.engine, agent_id, actor=who)
            except UnknownAgent as exc:
                raise HTTPException(404, f"unknown agent '{agent_id}'") from exc
            hit = (time.monotonic(), pack, html, None)
        if pdf and state.settings.low_memory:
            raise HTTPException(
                503,
                "PDF rendering is switched off on this deployment (low-memory mode: no headless "
                "browser). The HTML pack is complete; a sample PDF is in the repository under "
                "docs/samples/.",
            )
        if pdf and hit[3] is None:
            try:
                data = html_to_pdf(
                    hit[2], document_name=hit[1].document_name, footer_note=hit[1].disclaimer
                )
            except PdfUnavailable as exc:
                raise HTTPException(503, str(exc)) from exc
            hit = (hit[0], hit[1], hit[2], data)
        _cache[key] = hit
        return hit[1], hit[2], hit[3] or b""


def pack_of(pdf: bool):
    def dependency(agent_id: str, state: State, who: Actor):
        return _pack(state, agent_id, who, pdf=pdf)

    return Depends(dependency)


Rendered = Annotated[tuple[EvidencePack, str, bytes], pack_of(pdf=False)]
RenderedPdf = Annotated[tuple[EvidencePack, str, bytes], pack_of(pdf=True)]


@router.get("/agents/{agent_id}/evidence")
def evidence(rendered: Rendered) -> EvidencePack:
    """The evidence pack as data: every figure the HTML and PDF show."""
    return rendered[0]


@router.get("/agents/{agent_id}/evidence.html", response_class=HTMLResponse)
def evidence_html(rendered: Rendered) -> str:
    return rendered[1]


@router.get("/agents/{agent_id}/evidence.pdf")
def evidence_pdf(agent_id: str, rendered: RenderedPdf) -> Response:
    """PDF with the document name in the header and `Page X of Y` in the footer."""
    return Response(
        rendered[2],
        media_type="application/pdf",
        headers={"Content-Disposition": f'attachment; filename="evidence-pack-{agent_id}.pdf"'},
    )
