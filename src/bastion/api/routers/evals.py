"""Eval results: the scoreboard written by `make eval` (FR-60)."""

import json

from fastapi import APIRouter, HTTPException

from bastion.config import REPO_ROOT

router = APIRouter(tags=["evals"])
RESULTS_PATH = REPO_ROOT / "evals" / "results" / "latest.json"


@router.get("/evals/latest")
def latest() -> dict:
    """The most recent eval run on this installation: thresholds, metrics and every case."""
    if not RESULTS_PATH.is_file():
        raise HTTPException(404, "No eval results yet. Run `make eval`.")
    return json.loads(RESULTS_PATH.read_text(encoding="utf-8"))
