"""Smoke test for a running Bastion (container or `make serve`). Standard library only.

    python scripts/smoke.py                 # health + one governed scenario + audit verification
    python scripts/smoke.py --health-only   # used as the container HEALTHCHECK

Checks the API on 127.0.0.1:8000 and the console on 127.0.0.1:$PORT (8501 by default).
"""

import json
import os
import sys
import time
import urllib.request

API = os.environ.get("BASTION_API_URL", "http://127.0.0.1:8000")
CONSOLE = f"http://127.0.0.1:{os.environ.get('PORT', '8501')}"


def call(url: str, body: dict | None = None) -> tuple[int, str]:
    data = json.dumps(body).encode() if body is not None else None
    request = urllib.request.Request(url, data=data, headers={"content-type": "application/json"})
    with urllib.request.urlopen(request, timeout=20) as response:  # noqa: S310 - fixed local URLs
        return response.status, response.read().decode()


def health() -> None:
    status, body = call(f"{API}/healthz")
    assert status == 200 and json.loads(body) == {"status": "ok"}, f"API unhealthy: {status} {body}"
    status, body = call(f"{CONSOLE}/_stcore/health")
    assert status == 200 and body.strip() == "ok", f"console unhealthy: {status} {body}"


def scenario() -> None:
    """UC-03 in replay: injection → DENY R-007 → incident → kill switch. No API key involved."""
    meta = json.loads(call(f"{API}/meta")[1])
    assert meta["mode"] == "replay", f"smoke test expects replay mode, got {meta['mode']}"
    run = json.loads(call(f"{API}/runs", {"scenario": "uc03"})[1])
    deadline = time.time() + 120
    detail: dict = {}
    while time.time() < deadline:
        detail = json.loads(call(f"{API}/runs/{run['id']}")[1])
        if detail["status"] not in ("running", "interrupted"):
            break
        time.sleep(0.5)
    assert detail.get("status") == "halted", f"UC-03 should end halted: {detail}"
    assert any("DENY" in line and "R-007" in line for line in detail["timeline"]), detail
    assert any("KILL SWITCH" in line for line in detail["timeline"]), detail
    check = json.loads(call(f"{API}/audit/verify")[1])
    assert check["ok"], f"audit chain broken: {check}"
    print(f"UC-03 blocked and halted; audit chain intact ({check['events']} events).")
    status, html = call(f"{API}/agents/loan-ops-agent/evidence.html")
    assert status == 200 and "Framework mapping" in html, "evidence pack HTML was not produced"
    if not meta["pdf_enabled"]:
        print(f"Evidence pack HTML generated; PDF is off (low-memory, {meta['pii_engine']} PII).")
        return
    request = urllib.request.Request(f"{API}/agents/loan-ops-agent/evidence.pdf")
    with urllib.request.urlopen(request, timeout=120) as response:  # noqa: S310 - local URL
        pdf = response.read()
    assert response.status == 200 and pdf.startswith(b"%PDF"), "evidence PDF was not produced"
    print(f"Evidence pack PDF generated ({len(pdf) // 1024} kB).")


def main() -> int:
    try:
        health()
        if "--health-only" not in sys.argv:
            scenario()
    except Exception as exc:  # noqa: BLE001 - report and fail
        print(f"SMOKE FAILED: {exc}", file=sys.stderr)
        return 1
    print("smoke ok")
    return 0


if __name__ == "__main__":
    sys.exit(main())
