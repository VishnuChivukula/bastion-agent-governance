"""GovernedAnthropic: the only path by which Bastion-governed agents call a model (ADR-004).

Modes:
  replay  - answer from fixtures only; a miss raises ReplayMissError. No network, no key.
  record  - call the API and save the response as a fixture.
  live    - call the API, save nothing.

Governance controls (budget check, kill switch, usage recording, audit) attach as CallHooks:
`before_call` may raise to block the call; `after_call` records what happened.
"""

import time
from pathlib import Path
from typing import Any, Protocol

import yaml
from pydantic import BaseModel, Field

from bastion.config import Mode, Settings, get_settings
from bastion.llm.fixtures import FixtureStore, fixture_key


class ReplayMissError(RuntimeError):
    def __init__(self, key: str, model: str) -> None:
        super().__init__(
            f"No recorded fixture for this {model} request (key {key[:12]}…). "
            "Replay mode never calls the API. Run `make record` with an API key to record it."
        )
        self.key = key


class UnknownModelPriceError(KeyError):
    pass


class Usage(BaseModel):
    input_tokens: int = 0
    output_tokens: int = 0

    @property
    def total_tokens(self) -> int:
        return self.input_tokens + self.output_tokens


class LLMResponse(BaseModel):
    id: str = ""
    model: str
    content: list[dict[str, Any]] = Field(default_factory=list)
    stop_reason: str | None = None
    usage: Usage = Field(default_factory=Usage)
    cost_usd: float = 0.0
    replayed: bool = False
    fixture_key: str = ""

    @property
    def text(self) -> str:
        return "".join(b.get("text", "") for b in self.content if b.get("type") == "text")

    @property
    def tool_uses(self) -> list[dict[str, Any]]:
        return [b for b in self.content if b.get("type") == "tool_use"]


class CallRecord(BaseModel):
    agent_id: str
    run_id: str | None = None
    model: str
    mode: Mode
    usage: Usage
    cost_usd: float
    replayed: bool
    latency_ms: float
    stop_reason: str | None = None
    fixture_key: str


class CallHook(Protocol):
    def before_call(self, agent_id: str, run_id: str | None, model: str) -> None: ...

    def after_call(self, record: CallRecord) -> None: ...


class Transport(Protocol):
    def create(self, params: dict[str, Any]) -> dict[str, Any]: ...


class AnthropicTransport:
    """Real API transport. The SDK client is created lazily so replay never needs a key."""

    def __init__(self, api_key: str | None = None) -> None:
        self._api_key = api_key
        self._client: Any = None

    def create(self, params: dict[str, Any]) -> dict[str, Any]:
        if self._client is None:
            import anthropic

            self._client = (
                anthropic.Anthropic(api_key=self._api_key)
                if self._api_key
                else anthropic.Anthropic()
            )
        message = self._client.messages.create(**params)
        return message.model_dump(mode="json", exclude_none=True)


class Prices:
    def __init__(self, table: dict[str, dict[str, float]]) -> None:
        self._table = table

    @classmethod
    def load(cls, path: Path) -> "Prices":
        return cls(yaml.safe_load(Path(path).read_text(encoding="utf-8"))["models"])

    def cost(self, model: str, usage: Usage) -> float:
        try:
            price = self._table[model]
        except KeyError as exc:
            raise UnknownModelPriceError(
                f"No price for model '{model}' in config/prices.yaml; add it so budgets stay exact."
            ) from exc
        return round(
            usage.input_tokens * price["input_per_mtok"] / 1_000_000
            + usage.output_tokens * price["output_per_mtok"] / 1_000_000,
            8,
        )


class GovernedAnthropic:
    def __init__(
        self,
        agent_id: str,
        *,
        mode: Mode | None = None,
        settings: Settings | None = None,
        transport: Transport | None = None,
        store: FixtureStore | None = None,
        prices: Prices | None = None,
        hooks: list[CallHook] | None = None,
    ) -> None:
        self.settings = settings or get_settings()
        self.agent_id = agent_id
        self.mode: Mode = mode or self.settings.mode
        self.store = store or FixtureStore(self.settings.fixtures_dir)
        self.prices = prices or Prices.load(self.settings.prices_path)
        self.hooks = list(hooks or [])
        self._transport = transport

    def _get_transport(self) -> Transport:
        if self._transport is None:
            key = self.settings.anthropic_api_key
            self._transport = AnthropicTransport(key.get_secret_value() if key else None)
        return self._transport

    def create(
        self,
        *,
        model: str,
        messages: list[dict[str, Any]],
        max_tokens: int = 4096,
        run_id: str | None = None,
        **params: Any,
    ) -> LLMResponse:
        """Call the model. Extra keyword params (system, tools, output_config, ...) pass through.

        No `temperature` is sent: current models reject non-default sampling parameters, and
        determinism comes from replay fixtures instead (ADR-004).
        """
        request = {"model": model, "messages": messages, "max_tokens": max_tokens, **params}
        key = fixture_key(request)

        for hook in self.hooks:
            hook.before_call(self.agent_id, run_id, model)

        started = time.perf_counter()
        if self.mode == "replay":
            raw = self.store.load(key)
            if raw is None:
                raise ReplayMissError(key, model)
            replayed = True
        else:
            raw = self._get_transport().create(request)
            replayed = False
            if self.mode == "record":
                self.store.save(key, request, raw)
        latency_ms = (time.perf_counter() - started) * 1000

        usage = Usage(
            input_tokens=raw.get("usage", {}).get("input_tokens", 0),
            output_tokens=raw.get("usage", {}).get("output_tokens", 0),
        )
        response = LLMResponse(
            id=raw.get("id", ""),
            model=raw.get("model", model),
            content=raw.get("content", []),
            stop_reason=raw.get("stop_reason"),
            usage=usage,
            cost_usd=self.prices.cost(model, usage),
            replayed=replayed,
            fixture_key=key,
        )
        record = CallRecord(
            agent_id=self.agent_id,
            run_id=run_id,
            model=model,
            mode=self.mode,
            usage=usage,
            cost_usd=response.cost_usd,
            replayed=replayed,
            latency_ms=latency_ms,
            stop_reason=response.stop_reason,
            fixture_key=key,
        )
        for hook in self.hooks:
            hook.after_call(record)
        return response
