import pytest

from bastion.db import make_engine
from bastion.gateway.mcp_proxy import DownstreamPool, Gateway
from bastion.seed import DEMO_AGENT_ID, seed_demo
from demo.data.generate import build


@pytest.fixture(scope="session")
def anyio_backend():
    return "asyncio"


@pytest.fixture(scope="session")
def redactor():
    from bastion.gateway.redaction import get_redactor

    return get_redactor()


@pytest.fixture(scope="session")
def demo_db(tmp_path_factory):
    return build(tmp_path_factory.mktemp("demo") / "demo.db")


@pytest.fixture(scope="session")
async def pool(demo_db, anyio_backend):
    """One demo tools server subprocess shared by the whole test session."""
    pool = DownstreamPool({"BASTION_DEMO_DB": str(demo_db)})
    yield pool
    await pool.aclose()


@pytest.fixture
def engine(tmp_path):
    engine = make_engine(tmp_path / "bastion.db")
    yield engine
    engine.dispose()


class Harness:
    """A seeded gateway plus a run to call it under."""

    agent_id = DEMO_AGENT_ID

    def __init__(self, gateway: Gateway) -> None:
        self.gateway = gateway
        self.run_id = gateway.registry.start_run(self.agent_id, "test")

    async def call(self, tool, args=None, run_id=None):
        return await self.gateway.call_tool(self.agent_id, tool, args, run_id or self.run_id)

    def decisions(self):
        return self.gateway.audit.events(event_type="tool_decision", newest_first=False)


@pytest.fixture
def harness(engine, pool, redactor):
    seed_demo(engine)
    return Harness(Gateway(engine, pool=pool, redactor=redactor))
