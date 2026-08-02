"""Phase 1 bridge: exposes the local showrunner to the conversation app.

Throwaway. Deleted at Phase 2, when the showrunner is deployed as an HF Space
and the app reaches it over MCP instead.
"""

import logging
import os
from typing import Any

import httpx

from reachy_mini_conversation_app.tools.core_tools import Tool, ToolDependencies

logger = logging.getLogger(__name__)

BASE_URL = os.environ.get("SHOWRUNNER_URL", "http://127.0.0.1:7861")
TIMEOUT = 5.0


async def _post(path: str, payload: dict[str, Any]) -> dict[str, Any]:
    """POST to the showrunner. Always returns a dict, never raises."""
    try:
        async with httpx.AsyncClient(timeout=TIMEOUT) as client:
            response = await client.post(f"{BASE_URL}{path}", json=payload)
            response.raise_for_status()
            body = response.json()
        return body if isinstance(body, dict) else {"error": "malformed response"}
    except Exception as exc:  # noqa: BLE001 - never let this reach the conversation loop
        logger.warning("Showrunner call to %s failed: %s", path, exc)
        return {"error": f"showrunner unreachable: {exc}"}


class GetSetList(Tool):
    """Fetch the whole prepared set at the top of the bit."""

    name = "get_set_list"
    description = (
        "Get your prepared stand-up set about the loaded document. Call this once, "
        "when you start the bit. Returns an opener, a list of beats (each with a "
        "premise, punch, optional tags and a move hint), a closer, and callbacks."
    )
    parameters_schema = {"type": "object", "properties": {}, "required": []}

    async def __call__(self, deps: ToolDependencies, **kwargs: Any) -> dict[str, Any]:
        logger.info("Tool call: get_set_list")
        return await _post("/tools/get_set_list", {})


class GetFact(Tool):
    """Look up what the document actually said, for heckles."""

    name = "get_fact"
    description = (
        "Look up what the source document actually said about something. Use this "
        "when someone challenges a detail or asks about something not in your set."
    )
    parameters_schema = {
        "type": "object",
        "properties": {
            "query": {"type": "string", "description": "What to look up, e.g. 'payments'"},
        },
        "required": ["query"],
    }

    async def __call__(self, deps: ToolDependencies, **kwargs: Any) -> dict[str, Any]:
        query = kwargs.get("query", "")
        logger.info("Tool call: get_fact query=%s", query)
        return await _post("/tools/get_fact", {"query": query})


class MarkBeat(Tool):
    """Tell the operator console which beat just landed."""

    name = "mark_beat"
    description = (
        "Report that you have just delivered a beat, using its id. Call this right "
        "after each punch so the operator can follow along."
    )
    parameters_schema = {
        "type": "object",
        "properties": {
            "beat_id": {"type": "string", "description": "The beat id, e.g. 'b1'"},
        },
        "required": ["beat_id"],
    }

    async def __call__(self, deps: ToolDependencies, **kwargs: Any) -> dict[str, Any]:
        beat_id = kwargs.get("beat_id", "")
        logger.info("Tool call: mark_beat beat_id=%s", beat_id)
        return await _post("/tools/mark_beat", {"beat_id": beat_id})
