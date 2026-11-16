"""Low-memory mode for small hosts (S8b, ADR-010): the pattern PII engine, no headless browser,
and a console that does not load the server or data-frame stacks."""

import sqlite3
import subprocess
import sys

import pytest
import yaml
from streamlit.testing.v1 import AppTest

from bastion.config import REPO_ROOT, Settings
from bastion.gateway.redaction import (
    SUPPORTED_ENTITIES,
    LightRedactor,
    get_redactor,
    iban_valid,
    luhn_valid,
)
from tests.apiserver import ApiServer

AGENT = "loan-ops-agent"
APP = str(REPO_ROOT / "src" / "bastion" / "console" / "app.py")
COMBOS = [
    list(SUPPORTED_ENTITIES),
    ["EMAIL_ADDRESS", "PHONE_NUMBER", "IBAN_CODE"],  # R-001
    ["EMAIL_ADDRESS", "PHONE_NUMBER"],  # R-002
    ["IBAN_CODE", "CREDIT_CARD"],  # R-005 scan_input
]
TRICKY = [
    "Please check IBAN DE89370400440532013000 for the refund.",
    "IBAN DE89 3704 0044 0532 0130 00 REF 8812 was used",
    "IBAN GB82 WEST 1234 5698 7654 32, sort code 12-34-56",
    "not an iban: DE00370400440532013000",
    "Card 4111 1111 1111 1111 blocked",
    "card 4111-1111-1111-1111 and 5500 0000 0000 0004",
    "order number 4111 1111 1111 1112 is not a card",
    "Mail jo.bloggs+test@example.com or ops@bank.example, cc a_b@sub.domain.example",
    "Call +44 20 7946 0958 or (212) 555-0123 before 5pm",
    "Processed 1204 requests, 37 escalations, average handling time 412 seconds.",
    "ref 8812; limit 40000 to 60000; customer C-0021",
    "",
]


@pytest.fixture(scope="module")
def light():
    return LightRedactor()


def demo_strings(demo_db) -> list[str]:
    with sqlite3.connect(demo_db) as con:
        rows = [*con.execute("select * from customers"), *con.execute("select * from notes")]
    return sorted({str(value) for row in rows for value in row if isinstance(value, str)})


def eval_strings() -> list[str]:
    found: set[str] = set()

    def walk(node):
        if isinstance(node, str):
            found.add(node)
        elif isinstance(node, dict):
            for value in node.values():
                walk(value)
        elif isinstance(node, list):
            for value in node:
                walk(value)

    for path in (REPO_ROOT / "evals").glob("*/*.yaml"):
        walk(yaml.safe_load(path.read_text(encoding="utf-8")))
    return sorted(found)


def test_light_engine_agrees_with_presidio_on_all_demo_and_eval_text(redactor, light, demo_db):
    """Replay fixtures were recorded with Presidio. They stay valid only if the light engine
    masks exactly the same spans in everything the demo agent can see."""
    assert redactor.engine == "presidio" and light.engine == "light"
    texts = [*demo_strings(demo_db), *eval_strings(), *TRICKY]
    assert len(texts) > 300
    for entities in COMBOS:
        for text in texts:
            assert light.find(text, entities) == redactor.find(text, entities), (text, entities)


def test_light_engine_masks_and_counts(light):
    masked, counts = light.redact(
        {"to": "ops@bank.example", "body": ["IBAN DE89370400440532013000", {"n": 4}]},
        list(SUPPORTED_ENTITIES),
    )
    assert masked == {"to": "<EMAIL_ADDRESS>", "body": ["IBAN <IBAN_CODE>", {"n": 4}]}
    assert counts == {"EMAIL_ADDRESS": 1, "IBAN_CODE": 1}
    assert light.scan({"s": "Card 4111 1111 1111 1111"}, ["CREDIT_CARD"]) == {"CREDIT_CARD": 1}
    assert light.redact("ops@bank.example", []) == ("ops@bank.example", {})
    assert light.find("ops@bank.example", ["IBAN_CODE"]) == []


def test_checksums():
    assert luhn_valid("4111111111111111") and not luhn_valid("4111111111111112")
    assert not luhn_valid("4111x")
    assert iban_valid("DE89370400440532013000") and iban_valid("GB82WEST12345698765432")
    assert not iban_valid("DE00370400440532013000") and not iban_valid("DE8937")


def test_engine_selection():
    assert get_redactor(True).engine == "light" and get_redactor(True) is get_redactor(True)
    assert Settings(_env_file=None).low_memory is False
    assert Settings(_env_file=None, BASTION_LOW_MEMORY="true").low_memory is True


def run_python(code: str, **env: str) -> str:
    import os

    result = subprocess.run(  # noqa: S603 - fixed interpreter, test code
        [sys.executable, "-c", code],
        capture_output=True, text=True, cwd=REPO_ROOT, timeout=120,
        env={**os.environ, "BASTION_MODE": "replay", **env},
    )  # fmt: skip
    assert result.returncode == 0, result.stderr[-2000:]
    return result.stdout


def test_low_memory_api_process_never_loads_presidio_spacy_or_playwright():
    out = run_python(
        "import sys\n"
        "import bastion.api.main\n"
        "from bastion.gateway.redaction import get_redactor\n"
        "r = get_redactor()\n"
        "r.redact({'a': 'jo@example.com +44 20 7946 0958'}, ['EMAIL_ADDRESS', 'PHONE_NUMBER'])\n"
        "heavy = [m for m in ('presidio_analyzer', 'spacy', 'playwright', 'faker', 'pandas',"
        " 'anthropic') if m in sys.modules]\n"
        "print(r.engine, heavy)\n",
        BASTION_LOW_MEMORY="true",
    )
    assert out.strip() == "light []"


def test_console_modules_do_not_load_the_server_or_dataframe_stack():
    out = run_python(
        "import sys\n"
        "import bastion.console.client, bastion.console.common, bastion.console.format\n"
        "from bastion.console.views import (activity, approvals, evidence, incidents, overview,"
        " policies, redteam, registry, scenarios)\n"
        "print([m for m in ('fastapi', 'sqlalchemy', 'mcp', 'presidio_analyzer', 'spacy',"
        " 'langgraph', 'pandas', 'pyarrow') if m in sys.modules])\n"
    )
    assert out.strip() == "[]"


def test_tools_server_does_not_load_faker_when_the_data_exists(demo_db):
    out = run_python(
        "import sys, runpy\n"
        "import demo.tools_server.__main__ as server\n"
        "print(server._db().execute('select count(*) from customers').fetchone()[0],"
        " 'faker' in sys.modules)\n",
        BASTION_DEMO_DB=str(demo_db),
    )
    assert out.strip() == "50 False"


# --- the whole stack in low-memory mode ----------------------------------------------------------
@pytest.fixture(scope="module")
def small(tmp_path_factory):
    with ApiServer(tmp_path_factory.mktemp("small"), BASTION_LOW_MEMORY=True) as server:
        yield server


def test_meta_reports_the_profile(small):
    meta = small.anon.get("/meta").json()
    assert meta["low_memory"] is True and meta["pii_engine"] == "light"
    assert meta["pdf_enabled"] is False
    assert small.state.gateway.redactor.engine == "light"


def test_recorded_scenarios_replay_with_the_light_engine(small):
    lookup = small.run("uc02")
    assert lookup["status"] == "completed" and lookup["final_text"]
    first = next(e for e in lookup["events"] if e["type"] == "tool_decision")
    assert first["redactions"] == {"EMAIL_ADDRESS": 1, "PHONE_NUMBER": 1, "IBAN_CODE": 1}
    injected = small.run("uc03")
    assert injected["status"] == "halted"
    assert any("R-007" in line for line in injected["timeline"])
    approved = small.run("uc04")
    assert approved["status"] == "completed"


def test_evidence_is_html_only(small):
    html = small.anon.get(f"/agents/{AGENT}/evidence.html")
    assert html.status_code == 200 and "9. Framework mapping" in html.text
    pdf = small.anon.get(f"/agents/{AGENT}/evidence.pdf")
    assert pdf.status_code == 503 and "low-memory" in pdf.json()["detail"]


@pytest.mark.parametrize(
    "page", ["overview", "live_activity", "approvals", "policies", "red_team", "evidence"]
)
def test_console_pages_render_without_data_frames(small, page, monkeypatch):
    monkeypatch.setenv("BASTION_API_URL", small.url)
    monkeypatch.setenv("BASTION_CONSOLE_START_PAGE", page)
    at = AppTest.from_file(APP, default_timeout=60).run()
    assert not at.exception, at.exception
    assert not at.dataframe  # tables are markdown in this profile
    assert any("Small-host profile" in i.value for i in at.info)
    if page in ("overview", "live_activity", "red_team"):
        assert any(m.value.startswith("| ") and "|---|" in m.value for m in at.markdown)
    if page == "evidence":
        at.selectbox[0].set_value(AGENT).run()
        at.button[0].click().run()
        assert not at.exception
        assert any("PDF:" in c.value and "docs/samples" in c.value for c in at.caption)


def test_markdown_table_escapes_cells():
    from bastion.console.common import _cell

    assert _cell("a|b\nc") == "a\\|b c" and _cell(None) == "" and _cell(3) == "3"


def test_render_blueprint():
    blueprint = yaml.safe_load((REPO_ROOT / "render.yaml").read_text(encoding="utf-8"))
    (service,) = blueprint["services"]
    assert service["type"] == "web" and service["runtime"] == "docker"
    assert service["plan"] == "free" and service["healthCheckPath"] == "/_stcore/health"
    env = {item["key"]: item for item in service["envVars"]}
    assert env["BASTION_MODE"]["value"] == "replay"
    assert env["BASTION_LOW_MEMORY"]["value"] == "true"
    assert env["BASTION_PASSCODE"] == {"key": "BASTION_PASSCODE", "sync": False}  # a secret
    assert "ANTHROPIC_API_KEY" not in env
