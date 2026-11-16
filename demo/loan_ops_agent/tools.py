"""The Loan Ops Agent's own tool manifest (Anthropic tool definitions).

The agent ships with every tool of the bank's customer system, including the bulk export. That
is deliberate: the demo shows the gateway holding the line even when the agent knows about, and
tries to use, a tool its policy forbids. (Agents that build their tool list from gateway
discovery never see denied tools at all - see FR-11.)
"""

_CUSTOMER_ID = {"type": "string", "description": "Customer id, e.g. C-0007"}

TOOLS = [
    {
        "name": "lookup_customer",
        "description": "Look up a customer's profile: contact details, IBAN, segment, status "
        "and current credit limit.",
        "input_schema": {
            "type": "object",
            "properties": {"customer_id": _CUSTOMER_ID},
            "required": ["customer_id"],
        },
    },
    {
        "name": "get_customer_notes",
        "description": "Read the free-text service notes recorded for a customer.",
        "input_schema": {
            "type": "object",
            "properties": {"customer_id": _CUSTOMER_ID},
            "required": ["customer_id"],
        },
    },
    {
        "name": "update_credit_limit",
        "description": "Change a customer's credit limit. Needs the current limit, the new "
        "limit and the reason for the change.",
        "input_schema": {
            "type": "object",
            "properties": {
                "customer_id": _CUSTOMER_ID,
                "current_limit": {"type": "number"},
                "new_limit": {"type": "number"},
                "reason": {"type": "string"},
            },
            "required": ["customer_id", "current_limit", "new_limit", "reason"],
        },
    },
    {
        "name": "send_email",
        "description": "Send an email.",
        "input_schema": {
            "type": "object",
            "properties": {
                "to": {"type": "string"},
                "subject": {"type": "string"},
                "body": {"type": "string"},
            },
            "required": ["to", "subject", "body"],
        },
    },
    {
        "name": "export_customer_data",
        "description": "Bulk-export customer records to a destination address. Omit "
        "customer_ids to export every customer.",
        "input_schema": {
            "type": "object",
            "properties": {
                "destination": {"type": "string"},
                "customer_ids": {"type": "array", "items": {"type": "string"}},
            },
            "required": ["destination"],
        },
    },
]
