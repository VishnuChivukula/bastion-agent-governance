"""Content-addressed LLM fixtures for deterministic replay (ADR-004)."""

import hashlib
import json
from pathlib import Path
from typing import Any


def canonical_json(obj: Any) -> str:
    """Stable JSON: sorted keys, no insignificant whitespace, UTF-8 preserved."""
    return json.dumps(obj, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def _drop_none(obj: Any) -> Any:
    if isinstance(obj, dict):
        return {k: _drop_none(v) for k, v in obj.items() if v is not None}
    if isinstance(obj, list):
        return [_drop_none(v) for v in obj]
    return obj


def fixture_key(params: dict[str, Any]) -> str:
    """sha256 over every request parameter that can change the model's answer.

    The whole request is hashed (model, system, messages, tools, tool_choice, max_tokens,
    output_config, ...), so an unset optional parameter and an explicit None are the same key.
    """
    return hashlib.sha256(canonical_json(_drop_none(params)).encode("utf-8")).hexdigest()


class FixtureStore:
    def __init__(self, directory: Path) -> None:
        self.directory = Path(directory)

    def path(self, key: str) -> Path:
        return self.directory / f"{key}.json"

    def load(self, key: str) -> dict[str, Any] | None:
        path = self.path(key)
        if not path.exists():
            return None
        return json.loads(path.read_text(encoding="utf-8"))["response"]

    def save(self, key: str, params: dict[str, Any], response: dict[str, Any]) -> Path:
        self.directory.mkdir(parents=True, exist_ok=True)
        path = self.path(key)
        body = {"key": key, "request": _drop_none(params), "response": response}
        path.write_text(
            json.dumps(body, sort_keys=True, indent=1, ensure_ascii=False) + "\n", encoding="utf-8"
        )
        return path
