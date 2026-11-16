"""Argument hardening before policy evaluation (FR-13).

- Tool names match exactly. No trimming, no case folding: `Export_Customer_Data` and
  `export_customer_data ` are simply not the tool `export_customer_data`.
- Arguments are validated against the tool's JSON schema with unknown fields rejected at every
  level, whether or not the schema says so.
- Typing is strict: a numeric string (ASCII or unicode digits) is not a number, a bool is not a
  number, and NaN / infinity are rejected.
- Values are normalised so the same call always produces the same hash: integral floats become
  ints (60000.0 and 6e4 are 60000) and strings are NFC-normalised.
"""

import copy
import hashlib
import math
import re
import unicodedata
from typing import Any

from jsonschema import Draft202012Validator

from bastion.llm.fixtures import canonical_json

TOOL_NAME = re.compile(r"[a-z][a-z0-9_]{0,63}")
_FORBIDDEN_CONTROL = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")


class ArgumentError(Exception):
    """The call is malformed. The gateway denies it with reason `invalid_arguments`."""


def is_valid_tool_name(name: Any) -> bool:
    return isinstance(name, str) and TOOL_NAME.fullmatch(name) is not None


def harden_schema(schema: dict[str, Any]) -> dict[str, Any]:
    """Copy a JSON schema, closing every object so unknown fields are rejected."""
    hardened = copy.deepcopy(schema)

    def close(node: Any) -> None:
        if isinstance(node, dict):
            if node.get("type") == "object" or "properties" in node:
                node["additionalProperties"] = False
            for value in node.values():
                close(value)
        elif isinstance(node, list):
            for value in node:
                close(value)

    close(hardened)
    return hardened


def _normalise(value: Any, path: str) -> Any:
    if isinstance(value, bool) or value is None:
        return value
    if isinstance(value, float):
        if not math.isfinite(value):
            raise ArgumentError(f"{path}: non-finite number")
        return int(value) if value.is_integer() else value
    if isinstance(value, int):
        return value
    if isinstance(value, str):
        if _FORBIDDEN_CONTROL.search(value):
            raise ArgumentError(f"{path}: control characters are not allowed")
        return unicodedata.normalize("NFC", value)
    if isinstance(value, list):
        return [_normalise(item, f"{path}[{i}]") for i, item in enumerate(value)]
    if isinstance(value, dict):
        out = {}
        for key, item in value.items():
            if not isinstance(key, str):
                raise ArgumentError(f"{path}: non-string key")
            out[key] = _normalise(item, f"{path}.{key}" if path else key)
        return out
    raise ArgumentError(f"{path}: unsupported type {type(value).__name__}")


def validate_and_normalise(arguments: Any, schema: dict[str, Any]) -> dict[str, Any]:
    """Return normalised arguments, or raise ArgumentError with a short, value-free reason."""
    if arguments is None:
        arguments = {}
    if not isinstance(arguments, dict):
        raise ArgumentError("arguments must be an object")
    validator = Draft202012Validator(harden_schema(schema))
    errors = sorted(validator.iter_errors(arguments), key=lambda e: list(e.absolute_path))
    if errors:
        first = errors[0]
        where = ".".join(str(p) for p in first.absolute_path) or "arguments"
        # Report the failed keyword, never the offending value (it may be sensitive).
        if first.validator == "additionalProperties":
            raise ArgumentError(f"{where}: unknown field")
        raise ArgumentError(f"{where}: fails '{first.validator}' check")
    return _normalise(arguments, "")


def args_hash(arguments: dict[str, Any]) -> str:
    """Hash of normalised arguments. Approvals and grants are bound to this (ADR-002)."""
    return hashlib.sha256(canonical_json(arguments).encode("utf-8")).hexdigest()
