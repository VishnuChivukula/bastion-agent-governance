"""Scenario runs: start one of the scripted scenarios and follow it."""

from typing import Annotated

from fastapi import APIRouter, Header, HTTPException
from sqlalchemy import select

from bastion.api.auth import PASSCODE_HEADER, Actor, State, check_passcode
from bastion.api.routers.oversight import approval_out
from bastion.api.runs import RunBusy
from bastion.api.schemas import RunDetail, RunIn, RunOut, ScenarioOut
from bastion.api.state import AppState
from bastion.models import AuditEvent, Run
from demo.loan_ops_agent.run import audit_since, timeline_line
from demo.loan_ops_agent.scenarios import BY_ID, SCENARIOS

router = APIRouter(tags=["runs"])


@router.get("/scenarios")
def scenarios() -> list[ScenarioOut]:
    return [
        ScenarioOut(
            id=s.id,
            use_case=s.use_case,
            title=s.title,
            prompt=s.prompt,
            what_to_watch=s.what_to_watch,
            needs_approval=s.approver is not None or s.scripted,
        )
        for s in SCENARIOS
    ]


@router.post("/runs", status_code=202)
async def start_run(
    body: RunIn,
    state: State,
    who: Actor,
    passcode: Annotated[str | None, Header(alias=PASSCODE_HEADER)] = None,
) -> RunOut:
    """Start a scenario. In replay mode anyone may run the recorded scenarios (FR-82);
    record and live mode call the model API and need the passcode."""
    if body.scenario not in BY_ID:
        raise HTTPException(404, f"unknown scenario '{body.scenario}'")
    if state.settings.mode != "replay":
        check_passcode(state, passcode)
    try:
        run_id = state.runs.start(body.scenario, body.approver, who)
    except RunBusy as exc:
        raise HTTPException(409, str(exc)) from exc
    return RunOut.model_validate(state.gateway.registry.get_run(run_id))


@router.get("/runs")
def list_runs(state: State, limit: int = 30) -> list[RunOut]:
    rows = state.gateway.registry.list_runs(limit=min(max(limit, 1), 200))
    return [RunOut.model_validate(row) for row in rows]


def _seq_window(state: AppState, run: Run) -> tuple[int, int | None]:
    """Audit events of a run: from its `run_started` event to the next run's (runs are serial)."""
    with state.engine.connect() as conn:
        starts = conn.execute(
            select(AuditEvent.seq, AuditEvent.payload_json)
            .where(AuditEvent.event_type == "run_started", AuditEvent.agent_id == run.agent_id)
            .order_by(AuditEvent.seq)
        ).all()
    first = next((seq for seq, payload in starts if f'"{run.id}"' in payload), None)
    if first is None:
        return 0, 0
    later = [seq for seq, _ in starts if seq > first]
    return first, (later[0] if later else None)


@router.get("/runs/{run_id}")
def get_run(run_id: str, state: State) -> RunDetail:
    run = state.gateway.registry.get_run(run_id)
    if run is None:
        raise HTTPException(404, f"unknown run '{run_id}'")
    first, end = _seq_window(state, run)
    events = [e for e in audit_since(state.engine, first) if end is None or e["seq"] < end]
    events = events if first else []
    scenario = BY_ID.get(run.scenario or "")
    pending = [
        approval_out(a)
        for a in state.gateway.approvals.all(status="pending", agent_id=run.agent_id)
        if a.run_id == run.id
    ]
    return RunDetail(
        **RunOut.model_validate(run).model_dump(),
        title=scenario.title if scenario else "",
        what_to_watch=scenario.what_to_watch if scenario else "",
        prompt=scenario.prompt if scenario else "",
        error=state.runs.errors.get(run.id),
        pending=pending,
        timeline=[line for event in events if (line := timeline_line(event))],
        events=events,
    )
