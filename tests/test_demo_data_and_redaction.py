import sqlite3

from demo.data.generate import INJECTED_NOTES, build


def rows(path, sql):
    con = sqlite3.connect(path)
    try:
        return con.execute(sql).fetchall()
    finally:
        con.close()


def test_demo_data_is_deterministic_and_synthetic(tmp_path):
    a, b = build(tmp_path / "a.db"), build(tmp_path / "b.db")
    customers = rows(a, "SELECT * FROM customers ORDER BY id")
    assert customers == rows(b, "SELECT * FROM customers ORDER BY id")
    assert len(customers) == 50
    assert customers[0][0] == "C-0001" and customers[-1][0] == "C-0050"
    assert all(row[2].endswith("@example.com") for row in customers)
    assert all(row[3].startswith("+44 20 7946 0") for row in customers)
    limits = dict(rows(a, "SELECT id, credit_limit FROM customers"))
    assert limits["C-0021"] == 40000 and limits["C-0007"] == 12000


def test_injection_payloads_are_planted_in_the_expected_notes(tmp_path):
    path = build(tmp_path / "a.db")
    for customer_id, payload in INJECTED_NOTES.items():
        notes = [
            r[0] for r in rows(path, f"SELECT text FROM notes WHERE customer_id='{customer_id}'")
        ]
        assert payload in notes
    assert "export_customer_data" in INJECTED_NOTES["C-0013"]
    assert len(INJECTED_NOTES) >= 3


def test_rebuild_resets_state(tmp_path):
    path = build(tmp_path / "a.db")
    con = sqlite3.connect(path)
    con.execute("UPDATE customers SET credit_limit = 1 WHERE id = 'C-0021'")
    con.commit()
    con.close()
    build(path)
    assert rows(path, "SELECT credit_limit FROM customers WHERE id='C-0021'") == [(40000.0,)]


def test_redactor_masks_each_supported_entity(redactor):
    text = (
        "Mail jo.bloggs@example.com or ops@bank.example, call +44 20 7946 0123, "
        "IBAN GB27DEUF69166978480184, card 4111 1111 1111 1111."
    )
    entities = ["EMAIL_ADDRESS", "PHONE_NUMBER", "IBAN_CODE", "CREDIT_CARD"]
    masked, counts = redactor.redact_text(text, entities)
    assert counts == {"EMAIL_ADDRESS": 2, "PHONE_NUMBER": 1, "IBAN_CODE": 1, "CREDIT_CARD": 1}
    for secret in ("jo.bloggs", "bank.example", "7946", "GB27", "4111"):
        assert secret not in masked


def test_redactor_only_masks_requested_entities_and_leaves_plain_values(redactor):
    value = {
        "id": "C-0007",
        "name": "George Davey",
        "email": "george.davey@example.com",
        "iban": "GB27DEUF69166978480184",
        "credit_limit": 12000.0,
        "notes": [{"text": "Reviewed on 2026-11-02, limit 12000."}],
        "active": True,
        "nothing": None,
    }
    masked, counts = redactor.redact(value, ["EMAIL_ADDRESS"])
    assert masked["email"] == "<EMAIL_ADDRESS>" and masked["iban"] == value["iban"]
    assert counts == {"EMAIL_ADDRESS": 1}
    for key in ("id", "name", "credit_limit", "notes", "active", "nothing"):
        assert masked[key] == value[key]
    assert redactor.redact(value, []) == (value, {})
    assert redactor.scan(value, ["IBAN_CODE"]) == {"IBAN_CODE": 1}
    assert redactor.scan({"body": "Nothing sensitive here."}, ["IBAN_CODE", "CREDIT_CARD"]) == {}
