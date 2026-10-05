"""Hand a request from the room to the household's Hermes agent on the Pi.

Shared tool for the Reachy Mini conversation app (installed into its tools/ package). The app runs every tool
in its background tool manager and speaks when the result arrives, so a slow
agent turn doesn't freeze the conversation.

Config comes from the app instance .env (loaded before tools initialise):
  HOME_AGENT_URL  e.g. http://192.168.68.78:8642
  HOME_AGENT_KEY  the Hermes API_SERVER_KEY
"""

import logging
import os
import time
from typing import Any

import httpx

from reachy_mini_conversation_app.tools.core_tools import Tool, ToolDependencies

logger = logging.getLogger(__name__)

TIMEOUT_S = float(os.environ.get("HOME_AGENT_TIMEOUT_S", "240"))

# One Hermes session per app run keeps follow-ups ("send it", "what about Tuesday")
# in context; the session key scopes long-term memory to the household.
_SESSION_ID = f"reachy-{time.strftime('%Y%m%d-%H%M%S')}"
_SESSION_KEY = "reachy-household"

_client: httpx.AsyncClient | None = None


def _get_client() -> httpx.AsyncClient:
    global _client
    if _client is None or _client.is_closed:
        _client = httpx.AsyncClient(timeout=httpx.Timeout(TIMEOUT_S, connect=5.0))
    return _client


class AskHomeAgent(Tool):
    """Delegate real work to the home agent and return its spoken-style answer."""

    name = "ask_home_agent"
    description = (
        "Send a request to the home agent, which can research, plan, keep household "
        "notes and lists, set reminders, draft messages and follow through on tasks. "
        "Use for anything beyond small talk or a quick fact. It may take up to a "
        "minute; the answer comes back as short text to say aloud."
    )
    parameters_schema = {
        "type": "object",
        "properties": {
            "request": {
                "type": "string",
                "description": "What the person wants, in their own words, with any details they gave.",
            },
            "asked_by": {
                "type": "string",
                "description": "Name of the person asking, if known (e.g. a first name, or 'a guest').",
            },
        },
        "required": ["request"],
    }

    async def __call__(self, deps: ToolDependencies, **kwargs: Any) -> dict[str, Any]:
        url = os.environ.get("HOME_AGENT_URL", "").rstrip("/")
        key = os.environ.get("HOME_AGENT_KEY", "")
        request = (kwargs.get("request") or "").strip()
        asked_by = (kwargs.get("asked_by") or "unknown").strip()
        if not url or not key:
            return {"error": "The home agent isn't configured on this robot yet."}
        if not request:
            return {"error": "No request given."}

        logger.info("Tool call: ask_home_agent asked_by=%s request=%r", asked_by, request[:200])
        started = time.monotonic()
        try:
            response = await _get_client().post(
                f"{url}/v1/chat/completions",
                headers={
                    "Authorization": f"Bearer {key}",
                    "X-Hermes-Session-Id": _SESSION_ID,
                    "X-Hermes-Session-Key": _SESSION_KEY,
                },
                json={
                    "model": "hermes-agent",
                    "messages": [{"role": "user", "content": f"[Asked by {asked_by}, via Reachy] {request}"}],
                },
            )
            response.raise_for_status()
            answer = response.json()["choices"][0]["message"]["content"].strip()
        except Exception as exc:  # noqa: BLE001 - never let this reach the conversation loop
            logger.warning("ask_home_agent failed after %.1fs: %s", time.monotonic() - started, exc)
            return {"error": f"Couldn't reach the home agent: {type(exc).__name__}"}

        logger.info("ask_home_agent answered in %.1fs", time.monotonic() - started)
        return {"answer": answer}
