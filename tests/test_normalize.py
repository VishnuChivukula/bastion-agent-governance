import pytest

from bastion.gateway.normalize import (
    ArgumentError,
    args_hash,
    harden_schema,
    is_valid_tool_name,
    validate_and_normalise,
)

SCHEMA = {
    "type": "object",
    "properties": {
        "customer_id": {"type": "string", "pattern": r"^C-\d{4}$"},
        "new_limit": {"type": "number", "exclusiveMinimum": 0},
        "meta": {"type": "object", "properties": {"note": {"type": "string"}}},
        "ids": {"type": "array", "items": {"type": "string"}},
    },
    "required": ["customer_id"],
}


@pytest.mark.parametrize("name", ["lookup_customer", "a", "send_email2"])
def test_valid_tool_names(name):
    assert is_valid_tool_name(name)


@pytest.mark.parametrize(
    "name",
    ["Lookup_customer", "lookup_customer ", " lookup", "lookup-customer", "", "1abc", None, 5,
     "lookup\n", "ｌookup", "a" * 65, "lookup.customer", "lookup/../x"],
)  # fmt: skip
def test_invalid_tool_names(name):
    assert not is_valid_tool_name(name)


def test_integral_floats_normalise_to_ints_and_hash_equal():
    a = validate_and_normalise({"customer_id": "C-0001", "new_limit": 6e4}, SCHEMA)
    b = validate_and_normalise({"new_limit": 60000, "customer_id": "C-0001"}, SCHEMA)
    assert a == b and isinstance(a["new_limit"], int)
    assert args_hash(a) == args_hash(b)
    c = validate_and_normalise({"customer_id": "C-0001", "new_limit": 60000.5}, SCHEMA)
    assert c["new_limit"] == 60000.5 and args_hash(c) != args_hash(a)


def test_strings_are_nfc_normalised():
    composed = validate_and_normalise({"customer_id": "C-0001", "ids": ["café"]}, SCHEMA)
    decomposed = validate_and_normalise({"customer_id": "C-0001", "ids": ["café"]}, SCHEMA)
    assert args_hash(composed) == args_hash(decomposed)


@pytest.mark.parametrize(
    ("args", "fragment"),
    [
        ({"customer_id": "C-0001", "new_limit": "60000"}, "new_limit: fails 'type'"),
        ({"customer_id": "C-0001", "new_limit": "６００００"}, "new_limit: fails 'type'"),
        ({"customer_id": "C-0001", "new_limit": True}, "new_limit: fails 'type'"),
        ({"customer_id": "C-0001", "new_limit": -1}, "exclusiveMinimum"),
        ({"customer_id": "C-0001", "approved": True}, "unknown field"),
        ({"customer_id": "C-0001", "meta": {"note": "x", "admin": True}}, "meta: unknown field"),
        ({"customer_id": "c-0001"}, "customer_id: fails 'pattern'"),
        ({}, "fails 'required'"),
        ({"customer_id": "C-0001", "new_limit": float("nan")}, "non-finite"),
        ({"customer_id": "C-0001", "ids": ["ok", "bad\x00"]}, "ids[1]: control characters"),
        ("not an object", "must be an object"),
        ([1, 2], "must be an object"),
    ],
)
def test_rejections_name_the_field_but_not_the_value(args, fragment):
    with pytest.raises(ArgumentError, match=fragment.replace("[", r"\[").replace("]", r"\]")):
        validate_and_normalise(args, SCHEMA)


def test_none_arguments_mean_empty_object():
    assert validate_and_normalise(None, {"type": "object", "properties": {}}) == {}


def test_unsupported_value_types_are_rejected():
    with pytest.raises(ArgumentError, match="unsupported type"):
        validate_and_normalise({"x": object()}, {})
    with pytest.raises(ArgumentError, match="non-string key"):
        validate_and_normalise({"m": {1: "a"}}, {})


def test_harden_schema_closes_nested_objects_without_mutating_the_original():
    hardened = harden_schema(SCHEMA)
    assert hardened["additionalProperties"] is False
    assert hardened["properties"]["meta"]["additionalProperties"] is False
    assert "additionalProperties" not in SCHEMA
    open_schema = {"type": "object", "properties": {}, "additionalProperties": True}
    assert harden_schema(open_schema)["additionalProperties"] is False
