"""Control-plane API (FR-80). One process serves the REST API and the MCP gateway at `/mcp`.

uvicorn bastion.api.main:app --port 8000
"""

from contextlib import asynccontextmanager

from fastapi import FastAPI

from bastion import DISCLAIMER, __version__
from bastion.api.auth import State
from bastion.api.routers import (
    agents,
    audit,
    evals,
    evidence,
    oversight,
    policies,
    registry,
    runs,
)
from bastion.api.schemas import Meta
from bastion.api.state import build_state
from bastion.config import Settings, get_settings
from bastion.gateway.policy_engine import content_hash
from bastion.gateway.server import build_mcp_route
from bastion.seed import DEMO_AGENT_ID, DEMO_POLICY


def _seed_policy_in_force(state) -> bool:
    row = state.gateway.policies.active_row(DEMO_AGENT_ID)
    return row is None or row.content_hash == content_hash(DEMO_POLICY.read_text(encoding="utf-8"))


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or get_settings()

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        state = build_state(settings)
        app.state.bastion = state
        route, session_manager = build_mcp_route(state.gateway)
        app.router.routes.append(route)
        async with session_manager.run():
            try:
                yield
            finally:
                await state.runs.aclose()
                await state.gateway.aclose()
                app.router.routes.remove(route)
                state.engine.dispose()

    app = FastAPI(
        title="Bastion control-plane API",
        version=__version__,
        description=f"Runtime governance control plane for AI agents. {DISCLAIMER}",
        lifespan=lifespan,
    )

    @app.get("/healthz", tags=["meta"])
    def healthz() -> dict[str, str]:
        return {"status": "ok"}

    @app.get("/meta", tags=["meta"])
    def meta(state: State) -> Meta:
        return Meta(
            version=__version__,
            mode=state.settings.mode,
            mutations_enabled=state.settings.effective_passcode is not None,
            local_dev=state.settings.local_dev and state.settings.passcode is None,
            disclaimer=DISCLAIMER,
            demo_policy_is_seed=_seed_policy_in_force(state),
        )

    for module in (agents, registry, policies, oversight, runs, audit, evals, evidence):
        app.include_router(module.router)
    return app


def app() -> FastAPI:  # uvicorn --factory bastion.api.main:app
    return create_app()
