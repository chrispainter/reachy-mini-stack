"""For gpt-live-1 (no tool calling): pick an emotion for what Reachy just said, off the critical path."""

import httpx

from reachy_voice.body_policy import EMOTIONS

_PROMPT = (
    "You choose a body expression for a small friendly household robot, based on the line it just "
    "said. Reply with exactly one word from this list, or 'none' if no expression fits or the line "
    "is neutral (prefer 'none' most of the time): " + ", ".join(EMOTIONS)
)


class ExpressionPicker:
    def __init__(self, api_key: str, model: str = "gpt-5.4-nano", transport: httpx.AsyncBaseTransport | None = None,
                 timeout_s: float = 3.0) -> None:
        self._key, self._model = api_key, model
        self._client = httpx.AsyncClient(transport=transport, timeout=timeout_s)

    async def pick(self, text: str) -> str | None:
        if not text.strip():
            return None
        try:
            response = await self._client.post(
                "https://api.openai.com/v1/chat/completions",
                headers={"Authorization": f"Bearer {self._key}"},
                json={"model": self._model, "messages": [
                    {"role": "system", "content": _PROMPT},
                    {"role": "user", "content": text.strip()[:500]},
                ]},
            )
            response.raise_for_status()
            word = str(response.json()["choices"][0]["message"]["content"]).strip().lower()
        except Exception:  # noqa: BLE001 - an expression is optional; never fail the conversation
            return None
        return word if word in EMOTIONS else None

    async def aclose(self) -> None:
        await self._client.aclose()
