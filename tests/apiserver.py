"""A real control-plane API on a local port, for API and console tests."""

import socket
import threading
import time
from pathlib import Path

import httpx
import uvicorn

from bastion.api.auth import ACTOR_HEADER, PASSCODE_HEADER
from bastion.api.main import create_app
from bastion.config import Settings

PASSCODE = "test-passcode"
DONE = ("completed", "halted", "failed")


class ApiServer:
    def __init__(self, workdir: Path, *, passcode: str | None = PASSCODE, **overrides) -> None:
        with socket.socket() as sock:
            sock.bind(("127.0.0.1", 0))
            self.port = sock.getsockname()[1]
        self.url = f"http://127.0.0.1:{self.port}"
        self.settings = Settings(
            _env_file=None,
            BASTION_MODE="replay",
            ANTHROPIC_API_KEY=None,
            BASTION_PASSCODE=passcode,
            BASTION_DB_PATH=workdir / "bastion.db",
            BASTION_API_URL=self.url,
            **overrides,
        )
        self.app = create_app(self.settings)
        config = uvicorn.Config(self.app, host="127.0.0.1", port=self.port, log_level="error")
        self._server = uvicorn.Server(config)
        self._thread = threading.Thread(target=self._server.run, daemon=True)

    def __enter__(self) -> "ApiServer":
        self._thread.start()
        deadline = time.time() + 30
        while not self._server.started and time.time() < deadline:
            time.sleep(0.05)
        assert self._server.started, "API did not start"
        self.anon = httpx.Client(base_url=self.url, timeout=60)
        self.admin = httpx.Client(
            base_url=self.url,
            timeout=60,
            headers={PASSCODE_HEADER: PASSCODE, ACTOR_HEADER: "approver@bank.example"},
        )
        return self

    def __exit__(self, *exc: object) -> None:
        self.anon.close()
        self.admin.close()
        self._server.should_exit = True
        self._thread.join(timeout=15)

    @property
    def state(self):
        return self.app.state.bastion

    def run(self, scenario: str, approver: str = "scripted", until=DONE) -> dict:
        """Start a scenario and wait until it reaches one of the `until` statuses."""
        started = self.anon.post("/runs", json={"scenario": scenario, "approver": approver})
        assert started.status_code == 202, started.text
        return self.wait(started.json()["id"], until)

    def wait(self, run_id: str, until=DONE) -> dict:
        deadline = time.time() + 90
        detail: dict = {}
        while time.time() < deadline:
            detail = self.anon.get(f"/runs/{run_id}").json()
            parked = detail["status"] == "interrupted" and detail["pending"]
            finished = detail["status"] != "interrupted" and self.state.runs.busy() != run_id
            if detail["status"] in until and (parked or finished):
                return detail
            time.sleep(0.05)
        raise AssertionError(f"run {run_id} did not reach {until}: {detail}")
