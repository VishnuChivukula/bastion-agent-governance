"""Passcode guard for mutating routes (FR-82). There is no user model in v0.1: one shared
passcode, compared in constant time. With no passcode configured, mutating routes are disabled.
"""

import hmac
from typing import Annotated

from fastapi import Depends, Header, HTTPException

from bastion.api.state import AppState, get_state

PASSCODE_HEADER = "X-Bastion-Passcode"
ACTOR_HEADER = "X-Bastion-Actor"
DEFAULT_ACTOR = "console-user"


def check_passcode(state: AppState, supplied: str | None) -> None:
    expected = state.settings.effective_passcode
    if expected is None:
        raise HTTPException(
            403, "Mutating actions are disabled: no BASTION_PASSCODE is configured on this server."
        )
    if not supplied or not hmac.compare_digest(supplied.encode(), expected.encode()):
        state.gateway.audit.append(
            "passcode_rejected", actor="anonymous", payload={"supplied": bool(supplied)}
        )
        raise HTTPException(401, "A valid passcode is required for this action.")


def require_passcode(
    state: Annotated[AppState, Depends(get_state)],
    passcode: Annotated[str | None, Header(alias=PASSCODE_HEADER)] = None,
) -> None:
    check_passcode(state, passcode)


def actor(name: Annotated[str | None, Header(alias=ACTOR_HEADER)] = None) -> str:
    """Who the console user says they are. Recorded in the audit log; not authenticated."""
    cleaned = " ".join((name or "").split())[:80]
    return cleaned or DEFAULT_ACTOR


Guarded = Depends(require_passcode)
Actor = Annotated[str, Depends(actor)]
State = Annotated[AppState, Depends(get_state)]
