"""Evidence pack: data, HTML and PDF from the live records (S7, UC-09)."""

import io
import sqlite3

import pytest
from pypdf import PdfReader

from bastion.config import Settings
from bastion.db import make_engine
from bastion.evidence import generator
from bastion.evidence.cli import write_pack
from bastion.evidence.generator import MAPPING, UnknownAgent, collect, render_html
from bastion.evidence.pdf import footer_template, header_template
from bastion.seed import seed_demo
from tests.apiserver import ApiServer

AGENT = "loan-ops-agent"
SECTIONS = [
    "1. System description", "2. Risk classification and sign-off", "3. Controls in force",
    "4. Human oversight", "5. Robustness testing", "6. Incidents", "7. Usage and budgets",
    "8. Record-keeping", "9. Framework mapping", "10. Limitations",
]  # fmt: skip
DISCLAIMER = "Reference implementation; not production; not legal advice."


@pytest.fixture(scope="module")
def api(tmp_path_factory):
    with ApiServer(tmp_path_factory.mktemp("evidence")) as server:
        server.run("uc04")  # an approval that is granted and consumed
        server.run("uc03")  # a denial, an incident and the kill switch
        yield server


@pytest.fixture(scope="module")
def pack(api):
    return api.anon.get(f"/agents/{AGENT}/evidence").json()


@pytest.fixture(scope="module")
def html(api):
    return api.anon.get(f"/agents/{AGENT}/evidence.html").text


@pytest.fixture(scope="module")
def pdf(api):
    response = api.anon.get(f"/agents/{AGENT}/evidence.pdf")
    assert response.status_code == 200
    assert response.headers["content-type"] == "application/pdf"
    assert "evidence-pack-loan-ops-agent.pdf" in response.headers["content-disposition"]
    return PdfReader(io.BytesIO(response.content))


def test_pack_data_reflects_what_happened(pack):
    assert pack["document_name"] == "Bastion Evidence Pack — Loan Ops Agent"
    assert pack["agent"]["tier"] == "high" and pack["agent"]["status"] == "killed"
    assert pack["registration"]["classification"]["assessment"]["tier"] == "high"
    assert pack["registration"]["signed_off_by"]
    assert len(pack["policy"]["hash"]) == 64 and len(pack["policy"]["rules"]) == 7
    oversight = pack["oversight"]
    assert oversight["decisions"]["DENIED"] >= 1 and oversight["decisions"]["OK"] >= 1
    assert oversight["by_rule"]["R-007"] == {"DENIED": 1}
    assert oversight["redactions"] > 0
    assert oversight["kills"][-1]["what"] == "activated"
    assert [i["rule_id"] for i in pack["incidents"]][-1] == "IR-2"
    assert pack["usage"]["model_calls"] > 0 and pack["usage"]["tokens_in"] > 0
    assert pack["records"]["chain_ok"] and len(pack["records"]["head_hash"]) == 64
    assert pack["robustness"]["passed"] is True
    assert pack["disclaimer"] == DISCLAIMER


def test_html_has_every_section_the_hash_and_the_disclaimer(html, pack):
    for heading in SECTIONS:
        assert heading in html, heading
    assert html.count(DISCLAIMER) >= 2  # cover notice and closing notice
    assert pack["policy"]["hash"] in html and pack["records"]["head_hash"] in html
    assert "hash chain verified" in html
    assert "does not make a system compliant" in html
    assert "typically a deployer" in html and "All data is synthetic" in html
    assert "<script" not in html.lower()


def test_every_regulatory_reference_in_the_mapping_is_marked_verify(html, pack):
    table = html[html.index("9. Framework mapping") : html.index("10. Limitations")]
    rows = table.split("<tr><td>")[1:]
    assert len(rows) == len(pack["mapping"]) >= 9
    for row in rows:
        assert row.count("[VERIFY]") == 3, row
    for entry in MAPPING:  # clause level only: no Annex A control identifiers
        assert "A." not in entry["iso"] and "Annex A" not in entry["iso"]


def test_pdf_has_the_document_name_header_and_page_x_of_y_footer(pdf, pack):
    total = len(pdf.pages)
    assert total >= 5
    for number, page in enumerate(pdf.pages, start=1):
        text = " ".join(page.extract_text().split())
        assert pack["document_name"] in text, f"header missing on page {number}"
        assert f"Page {number} of {total}" in text, f"footer missing on page {number}"
    everything = " ".join(" ".join(p.extract_text().split()) for p in pdf.pages)
    assert "Limitations" in everything and "Framework mapping" in everything


def test_header_and_footer_templates_escape_their_text():
    assert "&lt;b&gt;" in header_template("<b>x")
    footer = footer_template("a & b")
    assert (
        "a &amp; b" in footer and 'class="pageNumber"' in footer and 'class="totalPages"' in footer
    )


def test_generation_is_audited_and_cached(api):
    events = api.anon.get("/audit/events", params={"event_type": "evidence_generated"}).json()
    assert len(events) == 1  # JSON, HTML and PDF above came from one generation
    assert events[0]["payload"]["chain_ok"] is True


def test_unknown_agent_is_a_404(api, tmp_path):
    for suffix in ("", ".html", ".pdf"):
        assert api.anon.get(f"/agents/nope/evidence{suffix}").status_code == 404
    with pytest.raises(UnknownAgent):
        collect(make_engine(tmp_path / "empty.db"), "nope")


def test_mapping_lists_only_capabilities_with_evidence(engine):
    seed_demo(engine)  # seeded directly: no card, no classification, no activity
    pack = collect(engine, AGENT)
    shown = {row["key"] for row in pack.mapping}
    assert {"policy", "audit", "budgets", "pack"} <= shown
    assert shown.isdisjoint({"classification", "approvals", "killswitch", "incidents", "card"})
    assert "Kill switch" in pack.mapping_omitted
    html = render_html(pack)
    assert "No classification is on record" in html and "No incidents were opened" in html
    assert "No approvals were requested" in html


def test_agent_without_a_policy_and_without_eval_results(engine, monkeypatch, tmp_path):
    from bastion.registry.service import Registry

    Registry(engine).create_agent("bare-agent", name="Bare <Agent>", owner="o@bank.example")
    monkeypatch.setattr(generator, "EVAL_RESULTS", tmp_path / "missing.json")
    html = render_html(collect(engine, "bare-agent"))
    assert "No policy is in force" in html and "No eval results are available" in html
    assert "Bare &lt;Agent&gt;" in html and "Bare <Agent>" not in html  # escaped


def test_a_broken_audit_chain_is_on_the_cover(tmp_path):
    with ApiServer(tmp_path) as server:
        server.run("uc02")
        with sqlite3.connect(tmp_path / "bastion.db") as con:
            con.execute("update audit_events set actor = 'someone-else' where seq = 2")
        pack = server.anon.get(f"/agents/{AGENT}/evidence").json()
        assert pack["records"]["chain_ok"] is False and pack["records"]["first_broken_seq"] == 2
        html = server.anon.get(f"/agents/{AGENT}/evidence.html").text
        assert "HASH CHAIN BROKEN at event #2" in html


def test_cli_writes_html_and_pdf(tmp_path):
    settings = Settings(
        _env_file=None, BASTION_MODE="replay", ANTHROPIC_API_KEY=None,
        BASTION_DB_PATH=tmp_path / "bastion.db",
    )  # fmt: skip
    html_path, pdf_path, pages = write_pack(AGENT, tmp_path / "out", settings=settings)
    assert html_path.read_text(encoding="utf-8").count(DISCLAIMER) >= 2
    assert pdf_path.read_bytes().startswith(b"%PDF") and pages == len(PdfReader(pdf_path).pages)


def test_committed_sample_is_a_real_pack():
    from bastion.config import REPO_ROOT

    sample = REPO_ROOT / "docs" / "samples" / "evidence-pack-loan-ops-agent.pdf"
    reader = PdfReader(sample)
    first = " ".join(reader.pages[0].extract_text().split())
    assert "Bastion Evidence Pack — Loan Ops Agent" in first
    assert f"Page 1 of {len(reader.pages)}" in first and DISCLAIMER in first
