"""Scenario runs started from the API: background tasks around the demo `AgentRunner`.

One run at a time: every scenario starts by resetting the demo (bank data, kill switch,
open incidents, open approvals), so two concurrent runs would trample each other.
"""

import asyncio
import logging
from typing import TYPE_CHECKING

from bastion.llm.client import ReplayMissError
from bastion.models import Approval
from bastion.seed import DEMO_AGENT_ID

if TYPE_CHECKING:
    from bastion.api.state import AppState

log = logging.getLogger("bastion.runs")

REPLAY_MISS_TEXT = (
    "Replay mode has no recorded model response for this path, so the run stops here. "
    "Recordings cover the scripted scenarios with the seed policy and an approving approver; "
    "a rejection, or a changed policy, takes the agent somewhere that was never recorded. "
    "Everything the gateway decided up to this point is real and is in the audit log."
)


class RunBusy(Exception):
    pass


class RunRefused(Exception):
    pass


class RunManager:
    def __init__(self, state: "AppState") -> None:
        self.state = state
        self._runner = None
        self._tasks: dict[str, asyncio.Task] = {}
        self._scripted: set[str] = set()
        self.errors: dict[str, str] = {}

    @property
    def gateway(self):
        return self.state.gateway

    def runner(self):
        if self._runner is None:
            from demo.loan_ops_agent.run import AgentRunner

            self._runner = AgentRunner(
                self.gateway,
                self.state.gateway_url,
                checkpoint_path=self.state.checkpoint_path,
                settings=self.state.settings,
            )
        return self._runner

    def busy(self) -> str | None:
        for run_id, task in self._tasks.items():
            if not task.done():
                return run_id
        return None

    def _spawn(self, run_id: str, coro) -> None:
        async def guarded() -> None:
            try:
                await coro
            except ReplayMissError:
                self._end(run_id, "completed", REPLAY_MISS_TEXT)
            except Exception as exc:  # noqa: BLE001 - a failed run must not take the API down
                log.exception("run %s failed", run_id)
                # Details stay in the server log; the public API shows only the error type.
                self.errors[run_id] = f"The run failed ({type(exc).__name__}). See the server log."
                self._end(run_id, "failed", "")

        self._tasks[run_id] = asyncio.create_task(guarded(), name=f"run:{run_id}")

    def _end(self, run_id: str, status: str, text: str) -> None:
        run = self.gateway.registry.get_run(run_id)
        if run is not None and run.status != "halted":
            self.gateway.registry.set_run_status(run_id, status)
        if text:
            self.gateway.registry.set_run_text(run_id, text)

    # --- start -----------------------------------------------------------------------------------
    def start(self, scenario_id: str, approver: str, actor: str) -> str:
        from demo.loan_ops_agent.run import reset_demo_state
        from demo.loan_ops_agent.scenarios import BY_ID

        scenario = BY_ID[scenario_id]
        if (active := self.busy()) is not None:
            raise RunBusy(f"run {active} is still in progress")
        if self.gateway.killswitch.is_active("global"):
            raise RunBusy(
                "the global kill switch is active; it must be released (with the passcode) "
                "before scenarios can run"
            )
        if approver == "human" and self.state.settings.effective_passcode is None:
            raise RunRefused(
                "no passcode is configured on this server, so nobody could decide the "
                "approval; run with the scripted approver instead"
            )
        registry = self.gateway.registry
        for parked in registry.list_runs(limit=200):
            if parked.status in ("running", "interrupted"):  # abandoned by this new run
                registry.set_run_status(parked.id, "halted")
                registry.set_run_text(parked.id, "Superseded: a new scenario run was started.")
        reset_demo_state(self.gateway, self.state.demo_db, actor=f"demo-reset ({actor})")
        runner = self.runner()
        run_id = registry.start_run(DEMO_AGENT_ID, scenario.id)
        if approver == "scripted":
            self._scripted.add(run_id)
            coro = runner.run_scripted(scenario, run_id=run_id)
        elif scenario.scripted:
            coro = runner.swap_begin(scenario, run_id)
        else:
            coro = runner.start(scenario, run_id=run_id)
        self._spawn(run_id, coro)
        return run_id

    # --- resume ----------------------------------------------------------------------------------
    def on_decision(self, approval: Approval) -> str | None:
        """An approver decided. If that was the last open decision of a parked run, resume it."""
        from demo.loan_ops_agent.scenarios import BY_ID

        run_id = approval.run_id
        if not run_id or run_id in self._scripted or self.busy() == run_id:
            return None
        run = self.gateway.registry.get_run(run_id)
        if run is None or run.status != "interrupted" or run.scenario not in BY_ID:
            return None
        mine = [a for a in self.gateway.approvals.all(agent_id=run.agent_id) if a.run_id == run_id]
        if any(a.status == "pending" for a in mine):
            return None
        scenario = BY_ID[run.scenario]
        if scenario.scripted:
            coro = self.runner().swap_finish(scenario, run_id)
        else:
            decisions = {
                a.id: {"approved": a.status == "approved", "reason": a.reason or ""} for a in mine
            }
            coro = self.runner().resume(scenario, run_id, decisions)
        self._spawn(run_id, coro)
        return run_id

    async def wait(self, run_id: str) -> None:
        """Wait for the current task of a run (tests and the CLI use this)."""
        task = self._tasks.get(run_id)
        if task is not None:
            await task

    async def aclose(self) -> None:
        for task in self._tasks.values():
            task.cancel()
        await asyncio.gather(*self._tasks.values(), return_exceptions=True)
