"""Control-plane API (FR-80). One process serves the REST API and the MCP gateway at `/mcp`.

uvicorn bastion.api.main:app --port 8000
"""

from contextlib import asynccontextmanager

from fastapi import FastAPI

from bastion import DISCLAIMER, __version__
from bastion.api.auth import State
from bastion.api.routers import agents, audit, evidence, oversight, policies, runs
from bastion.api.schemas import Meta
from bastion.api.state import build_state
from bastion.config import Settings, get_settings
from bastion.gateway.server import build_mcp_route


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
        )

    for module in (agents, policies, oversight, runs, audit, evidence):
        app.include_router(module.router)
    return app


def app() -> FastAPI:  # uvicorn --factory bastion.api.main:app
    return create_app()
