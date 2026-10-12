import asyncio
import json

import httpx
import pytest

from reachy_voice.expression_picker import ExpressionPicker


def picker(handler):
    return ExpressionPicker("k", transport=httpx.MockTransport(handler))


def reply(text):
    return httpx.Response(200, json={"choices": [{"message": {"content": text}}]})


def test_picks_a_known_emotion_and_sends_the_line():
    seen = {}

    def handler(request):
        seen["body"] = json.loads(request.content)
        seen["auth"] = request.headers["authorization"]
        return reply(" Happy \n")

    assert asyncio.run(picker(handler).pick("That's wonderful news!")) == "happy"
    assert seen["auth"] == "Bearer k" and seen["body"]["model"] == "gpt-5.4-nano"
    assert "That's wonderful news!" in seen["body"]["messages"][-1]["content"]


@pytest.mark.parametrize("content", ["none", "ecstatic", "", "I think happy and sad"])
def test_none_or_unknown_gives_none(content):
    assert asyncio.run(picker(lambda r: reply(content)).pick("hello")) is None


def test_errors_and_blank_text_give_none():
    assert asyncio.run(picker(lambda r: httpx.Response(500)).pick("hello")) is None

    def boom(request):
        raise httpx.ConnectTimeout("slow")

    assert asyncio.run(picker(boom).pick("hello")) is None
    calls = []
    assert asyncio.run(picker(lambda r: calls.append(1) or reply("happy")).pick("   ")) is None
    assert calls == []


def test_failure_is_logged_without_secrets_and_gives_none():
    events = []

    class Log:
        def write(self, event, **kw): events.append((event, kw))

    p = ExpressionPicker("sk-secret", transport=httpx.MockTransport(lambda r: httpx.Response(401)), log=Log())
    assert asyncio.run(p.pick("private words")) is None
    assert events == [("expression_pick_failed", {"error": "HTTPStatusError"})]
