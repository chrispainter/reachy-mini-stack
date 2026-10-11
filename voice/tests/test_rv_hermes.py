import asyncio
import json

import httpx
import pytest

from reachy_voice.hermes import HermesClient, HermesError


def make(handler, url="http://pi:8642/", key="k"):
    return HermesClient(url, key, "gpt-5.4-nano", "openai-api", transport=httpx.MockTransport(handler))


def reply(text):
    return httpx.Response(200, json={"choices": [{"message": {"content": f"  {text}  "}}]})


def test_quick_lane_sends_model_and_provider_and_headers():
    seen = {}

    def handler(request):
        seen["url"] = str(request.url)
        seen["headers"] = request.headers
        seen["body"] = json.loads(request.content)
        return reply("Milk and eggs.")

    out = asyncio.run(make(handler).ask("what's on the list", "Sam", "quick", "sess-1"))
    assert out == "Milk and eggs."
    assert seen["url"] == "http://pi:8642/v1/chat/completions"
    assert seen["headers"]["authorization"] == "Bearer k"
    assert seen["headers"]["x-hermes-session-id"] == "sess-1"
    assert seen["headers"]["x-hermes-session-key"] == "reachy-household"
    assert seen["body"]["model"] == "gpt-5.4-nano" and seen["body"]["provider"] == "openai-api"
    assert seen["body"]["messages"][0]["content"] == "[Asked by Sam, via Reachy] what's on the list"


def test_task_lane_uses_gateway_default_model():
    seen = {}

    def handler(request):
        seen["body"] = json.loads(request.content)
        return reply("Planned.")

    asyncio.run(make(handler).ask("plan a trip", "", "task", "s"))
    assert seen["body"]["model"] == "hermes-agent" and "provider" not in seen["body"]
    assert seen["body"]["messages"][0]["content"].startswith("[Asked by unknown, via Reachy]")


@pytest.mark.parametrize("response", [httpx.Response(500, text="boom"), httpx.Response(200, json={"oops": 1})])
def test_bad_responses_raise_hermes_error(response):
    with pytest.raises(HermesError):
        asyncio.run(make(lambda r: response).ask("x", "a", "quick", "s"))


def test_connection_failure_raises_hermes_error():
    def handler(request):
        raise httpx.ConnectError("refused")

    with pytest.raises(HermesError, match="ConnectError"):
        asyncio.run(make(handler).ask("x", "a", "task", "s"))


def test_unconfigured_client_raises():
    with pytest.raises(HermesError, match="not configured"):
        asyncio.run(make(lambda r: reply("x"), url="", key="").ask("x", "a", "quick", "s"))
