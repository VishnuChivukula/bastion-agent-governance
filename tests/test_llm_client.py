import json

import pytest

from bastion.config import Settings
from bastion.llm import FixtureStore, GovernedAnthropic, ReplayMissError, fixture_key
from bastion.llm.client import CallRecord, Prices, UnknownModelPriceError, Usage

MODEL = "claude-haiku-5-5"
PRICES = Prices({MODEL: {"input_per_mtok": 0.10, "output_per_mtok": 0.50}})
MESSAGES = [{"role": "user", "content": "Summarise customer C-0007"}]


class FakeTransport:
    def __init__(self) -> None:
        self.calls: list[dict] = []

    def create(self, params: dict) -> dict:
        self.calls.append(params)
        return {
            "id": "msg_fake",
            "model": params["model"],
            "content": [
                {"type": "text", "text": "Looking that up."},
                {"type": "tool_use", "id": "tu_1", "name": "lookup_customer", "input": {"id": 7}},
            ],
            "stop_reason": "tool_use",
            "usage": {"input_tokens": 1000, "output_tokens": 200},
        }


class RecordingHook:
    def __init__(self, block: Exception | None = None) -> None:
        self.before: list[tuple] = []
        self.after: list[CallRecord] = []
        self.block = block

    def before_call(self, agent_id, run_id, model) -> None:
        self.before.append((agent_id, run_id, model))
        if self.block:
            raise self.block

    def after_call(self, record: CallRecord) -> None:
        self.after.append(record)


def make_client(tmp_path, mode, transport=None, hooks=None) -> GovernedAnthropic:
    return GovernedAnthropic(
        "loan-ops-agent",
        mode=mode,
        settings=Settings(_env_file=None),
        transport=transport,
        store=FixtureStore(tmp_path / "fixtures"),
        prices=PRICES,
        hooks=hooks,
    )


def test_record_then_replay_round_trip(tmp_path):
    transport = FakeTransport()
    recorded = make_client(tmp_path, "record", transport).create(model=MODEL, messages=MESSAGES)
    assert not recorded.replayed
    assert len(transport.calls) == 1

    replay_transport = FakeTransport()
    replayed = make_client(tmp_path, "replay", replay_transport).create(
        model=MODEL, messages=MESSAGES
    )
    assert replayed.replayed
    assert replay_transport.calls == []  # replay never touches the transport
    assert replayed.content == recorded.content
    assert replayed.text == "Looking that up."
    assert replayed.tool_uses[0]["name"] == "lookup_customer"
    assert replayed.cost_usd == recorded.cost_usd


def test_replay_miss_raises_with_record_hint(tmp_path):
    with pytest.raises(ReplayMissError, match="make record"):
        make_client(tmp_path, "replay", FakeTransport()).create(model=MODEL, messages=MESSAGES)


def test_replay_needs_no_api_key_or_sdk_client(tmp_path):
    client = make_client(tmp_path, "replay")  # no transport injected, no key in settings
    with pytest.raises(ReplayMissError):
        client.create(model=MODEL, messages=MESSAGES)
    assert client._transport is None


def test_live_mode_saves_no_fixture(tmp_path):
    make_client(tmp_path, "live", FakeTransport()).create(model=MODEL, messages=MESSAGES)
    assert not (tmp_path / "fixtures").exists()


def test_fixture_file_contains_request_and_response(tmp_path):
    response = make_client(tmp_path, "record", FakeTransport()).create(
        model=MODEL, messages=MESSAGES, system="You are a loan ops agent."
    )
    body = json.loads((tmp_path / "fixtures" / f"{response.fixture_key}.json").read_text())
    assert body["request"]["system"] == "You are a loan ops agent."
    assert body["response"]["stop_reason"] == "tool_use"


def test_fixture_key_is_order_independent_and_content_sensitive():
    a = {"model": MODEL, "messages": MESSAGES, "max_tokens": 10, "system": None}
    b = {"max_tokens": 10, "messages": MESSAGES, "model": MODEL}
    assert fixture_key(a) == fixture_key(b)
    assert fixture_key(a) != fixture_key({**b, "max_tokens": 11})
    assert fixture_key(a) != fixture_key({**b, "tools": [{"name": "x"}]})


def test_cost_from_price_table():
    cost = PRICES.cost(MODEL, Usage(input_tokens=1000, output_tokens=200))
    assert cost == pytest.approx(1000 * 0.10 / 1e6 + 200 * 0.50 / 1e6)


def test_unknown_model_price_is_an_error():
    with pytest.raises(UnknownModelPriceError):
        PRICES.cost("some-other-model", Usage(input_tokens=1))


def test_hooks_run_before_and_after(tmp_path):
    hook = RecordingHook()
    make_client(tmp_path, "live", FakeTransport(), [hook]).create(
        model=MODEL, messages=MESSAGES, run_id="run-1"
    )
    assert hook.before == [("loan-ops-agent", "run-1", MODEL)]
    record = hook.after[0]
    assert record.usage.total_tokens == 1200
    assert record.cost_usd > 0
    assert record.mode == "live" and not record.replayed


def test_blocking_hook_prevents_the_model_call(tmp_path):
    transport = FakeTransport()
    hook = RecordingHook(block=PermissionError("killswitch"))
    with pytest.raises(PermissionError):
        make_client(tmp_path, "live", transport, [hook]).create(model=MODEL, messages=MESSAGES)
    assert transport.calls == []
    assert hook.after == []


def test_shipped_price_table_covers_configured_models():
    settings = Settings(_env_file=None)
    prices = Prices.load(settings.prices_path)
    for model in (settings.model_fast, settings.model_smart):
        assert prices.cost(model, Usage(input_tokens=1_000_000)) > 0
