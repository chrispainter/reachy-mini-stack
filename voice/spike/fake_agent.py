"""Stands in for Hermes so talk-while-tool behaviour can be tested deterministically."""

import asyncio

FAKE_ANSWER = "The grocery list has milk, eggs and coffee."


async def fake_home_agent(request: str, delay_s: float = 20.0) -> str:
    await asyncio.sleep(delay_s)
    return FAKE_ANSWER
