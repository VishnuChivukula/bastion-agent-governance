"""NFR-01: gateway overhead p95 < 50 ms locally, excluding the downstream tool."""

import statistics
import time

import pytest

pytestmark = pytest.mark.anyio


async def test_gateway_overhead_p95_is_under_50_ms(harness):
    calls = [
        ("lookup_customer", {"customer_id": "C-0007"}),
        ("get_customer_notes", {"customer_id": "C-0013"}),
        ("export_customer_data", {"destination": "x@external.example"}),
        ("send_email", {"to": "ops@bank.example", "subject": "Review", "body": "C-0007 done."}),
    ]
    await harness.gateway.list_tools(harness.agent_id)  # one-off: start the tools server
    overheads = []
    for i in range(28):  # stays under the 30-call session budget
        tool, args = calls[i % len(calls)]
        started = time.perf_counter()
        result = await harness.call(tool, args)
        wall_ms = (time.perf_counter() - started) * 1000
        overheads.append(wall_ms - result.downstream_ms)  # includes the audit write
    p95 = statistics.quantiles(overheads, n=20)[18]
    print(f"gateway overhead: median {statistics.median(overheads):.1f} ms, p95 {p95:.1f} ms")
    assert p95 < 50
