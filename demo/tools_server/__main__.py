"""Demo tools MCP server: the fictional bank's customer system (synthetic data only).

Spawned by the Bastion gateway over stdio. It has no governance of its own: every control is
applied by the gateway in front of it.
"""

import os
import sqlite3
from pathlib import Path
from typing import Annotated, Any

from mcp.server.mcpserver import MCPServer
from mcp.server.mcpserver.exceptions import ToolError
from pydantic import Field

DB_PATH = Path(os.environ.get("BASTION_DEMO_DB", "data/demo.db"))

CustomerId = Annotated[str, Field(pattern=r"^C-\d{4}$", description="Customer id, e.g. C-0007")]

server = MCPServer("loan-tools")


def _db() -> sqlite3.Connection:
    if not DB_PATH.exists():
        from demo.data.generate import build  # Faker is heavy: load it only when needed

        build(DB_PATH)
    con = sqlite3.connect(DB_PATH)
    con.row_factory = sqlite3.Row
    return con


def _customer(con: sqlite3.Connection, customer_id: str) -> sqlite3.Row:
    row = con.execute("SELECT * FROM customers WHERE id = ?", (customer_id,)).fetchone()
    if row is None:
        raise ToolError(f"Unknown customer {customer_id}")
    return row


@server.tool()
def lookup_customer(customer_id: CustomerId) -> dict[str, Any]:
    """Look up a customer's profile: contact details, IBAN, segment and credit limit."""
    with _db() as con:
        return dict(_customer(con, customer_id))


@server.tool()
def get_customer_notes(customer_id: CustomerId) -> dict[str, Any]:
    """Read the free-text service notes recorded for a customer."""
    with _db() as con:
        _customer(con, customer_id)
        rows = con.execute(
            "SELECT date, author, text FROM notes WHERE customer_id = ? ORDER BY date, id",
            (customer_id,),
        ).fetchall()
        return {"customer_id": customer_id, "notes": [dict(r) for r in rows]}


@server.tool()
def update_credit_limit(
    customer_id: CustomerId,
    current_limit: Annotated[float, Field(ge=0, description="The limit as it is now")],
    new_limit: Annotated[float, Field(gt=0, le=10_000_000, description="The requested limit")],
    reason: Annotated[str, Field(min_length=3, max_length=500)],
) -> dict[str, Any]:
    """Change a customer's credit limit. State the current limit, the new limit and the reason."""
    with _db() as con:
        actual = _customer(con, customer_id)["credit_limit"]
        if abs(actual - current_limit) > 0.005:
            raise ToolError(f"current_limit does not match the record ({actual:g})")
        con.execute("UPDATE customers SET credit_limit = ? WHERE id = ?", (new_limit, customer_id))
        return {"customer_id": customer_id, "old_limit": actual, "new_limit": new_limit}


@server.tool()
def send_email(
    to: Annotated[str, Field(pattern=r"^[^@\s]+@[^@\s]+$", max_length=254)],
    subject: Annotated[str, Field(max_length=200)],
    body: Annotated[str, Field(max_length=5000)],
) -> dict[str, Any]:
    """Send an email. (Demo: the message is written to an outbox table, never actually sent.)"""
    with _db() as con:
        cur = con.execute(
            "INSERT INTO outbox (kind, recipient, subject, body) VALUES ('email', ?, ?, ?)",
            (to, subject, body),
        )
        return {"queued": True, "outbox_id": cur.lastrowid, "to": to}


@server.tool()
def export_customer_data(
    destination: Annotated[str, Field(max_length=254)],
    customer_ids: list[CustomerId] | None = None,
) -> dict[str, Any]:
    """Bulk-export customer records to a destination. (Demo: written to the outbox table.)"""
    with _db() as con:
        if customer_ids:
            marks = ",".join("?" * len(customer_ids))
            sql = f"SELECT id FROM customers WHERE id IN ({marks})"  # noqa: S608
            rows = con.execute(sql, customer_ids).fetchall()
        else:
            rows = con.execute("SELECT id FROM customers").fetchall()
        con.execute(
            "INSERT INTO outbox (kind, recipient, subject, body) VALUES ('export', ?, ?, ?)",
            (destination, "customer export", f"{len(rows)} records"),
        )
        return {"exported": len(rows), "destination": destination}


if __name__ == "__main__":
    server.run("stdio")
