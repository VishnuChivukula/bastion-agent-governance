"""Everything the API process owns: database, gateway, demo data and the run manager."""

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from fastapi import Request
from sqlalchemy import Engine

from bastion.config import Settings
from bastion.db import make_engine
from bastion.gateway.mcp_proxy import Gateway
from bastion.llm.client import ReplayMissError
from bastion.registry.classification import ClassificationService
from bastion.seed import seed_demo, seed_demo_classified


@dataclass
class AppState:
    settings: Settings
    engine: Engine
    gateway: Gateway
    demo_db: Path
    checkpoint_path: Path
    runs: Any = field(default=None)  # RunManager; set in build_state (it needs the state)
    classification: Any = field(default=None)  # ClassificationService

    @property
    def gateway_url(self) -> str:
        """Where the demo agent reaches the gateway: this same process, over HTTP."""
        return self.settings.api_url.rstrip("/") + "/mcp"


def _seed(engine: Engine, settings: Settings) -> None:
    """Seed the demo agent. In replay mode it goes through the real classification and
    sign-off flow (answers come from fixtures); otherwise, or if the recording is missing, it
    is seeded directly so start-up never calls a model API."""
    if settings.mode == "replay":
        try:
            seed_demo_classified(engine, settings)
            return
        except ReplayMissError:
            pass
    seed_demo(engine)


def build_state(settings: Settings) -> AppState:
    from bastion.api.runs import RunManager
    from demo.data.generate import build as build_demo_data

    data_dir = Path(settings.db_path).parent
    engine = make_engine(settings.db_path)
    demo_db = data_dir / "demo.db"
    if settings.seed_on_start:
        _seed(engine, settings)
        if not demo_db.exists():
            build_demo_data(demo_db)
    state = AppState(
        settings=settings,
        engine=engine,
        gateway=Gateway(engine, demo_db=demo_db),
        demo_db=demo_db,
        checkpoint_path=data_dir / "checkpoints.db",
    )
    state.runs = RunManager(state)
    state.classification = ClassificationService(engine, state.gateway.audit, settings=settings)
    return state


def get_state(request: Request) -> AppState:
    return request.app.state.bastion
