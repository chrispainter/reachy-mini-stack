"""Client for the household's Hermes agent on the Pi (LAN only, bearer key)."""

import httpx

QUICK_TIMEOUT_S = 90.0
TASK_TIMEOUT_S = 300.0


class HermesError(Exception):
    pass


class HermesClient:
    def __init__(self, url: str, key: str, quick_model: str, quick_provider: str,
                 transport: httpx.AsyncBaseTransport | None = None) -> None:
        self._url = url.rstrip("/")
        self._key = key
        self._quick_model = quick_model
        self._quick_provider = quick_provider
        self._client = httpx.AsyncClient(transport=transport, timeout=httpx.Timeout(TASK_TIMEOUT_S, connect=5.0))

    async def ask(self, request: str, asked_by: str, lane: str, session_id: str) -> str:
        if not self._url or not self._key:
            raise HermesError("home agent not configured")
        body: dict = {
            "model": "hermes-agent",
            "messages": [{"role": "user", "content": f"[Asked by {asked_by or 'unknown'}, via Reachy] {request}"}],
        }
        if lane == "quick":
            # An explicit provider makes Hermes honour the per-request model (fast lane).
            body.update(model=self._quick_model, provider=self._quick_provider)
        headers = {
            "Authorization": f"Bearer {self._key}",
            "X-Hermes-Session-Id": session_id,
            "X-Hermes-Session-Key": "reachy-household",
        }
        timeout = QUICK_TIMEOUT_S if lane == "quick" else TASK_TIMEOUT_S
        try:
            response = await self._client.post(f"{self._url}/v1/chat/completions", json=body, headers=headers, timeout=timeout)
            response.raise_for_status()
            content = response.json()["choices"][0]["message"]["content"]
        except (httpx.HTTPError, KeyError, IndexError, TypeError, ValueError, AttributeError) as exc:
            raise HermesError(f"{type(exc).__name__}: {exc}") from exc
        if not isinstance(content, str):
            raise HermesError("empty or non-text reply from home agent")
        return content.strip()

    async def aclose(self) -> None:
        await self._client.aclose()
