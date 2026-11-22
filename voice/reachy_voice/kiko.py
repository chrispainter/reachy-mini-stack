"""Outbound client for the household Grok Bot, via a result mailbox.

The robot POSTs a job to the Bot's routine webhook, then polls the mailbox
until speech comes back. Nothing listens on the robot. Returned speech is
words to say: it is length-capped and never treated as a command.
"""

import asyncio
import re
import time
import uuid
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

import httpx

SPEECH_WORD_CAP = 60
SPEECH_CHAR_CAP = 600
POLL_INTERVAL_S = 3.0
_CONTROL = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")


class KikoError(Exception):
    pass


class KikoTimeout(KikoError):
    """The mailbox had no speech before KIKO_TIMEOUT_S."""


def bounded_timeout(timeout_s: float, pending_max_s: float) -> float:
    """Keep the wait inside the session pending window so the follow-up can be spoken."""
    ceiling = max(1.0, pending_max_s - 15.0)
    return min(max(1.0, timeout_s), ceiling)


def authorization_header(spec: str, key: str) -> tuple[str, str]:
    """Header name and value for a KIKO_*_AUTH_HEADER spec.

    The default ``Authorization: Bearer <key>`` is the Grok Bot routine webhook
    header: senders put the panel's key in ``Authorization: Bearer <key>``.
    A spec with no colon is a header name, and the value is the raw key.
    """
    raw = (spec or "").strip() or "Authorization: Bearer <key>"
    if ":" not in raw:
        return raw, key
    name, _, rest = raw.partition(":")
    name = name.strip()
    template = rest.strip()
    if "<key>" in template:
        return name, template.replace("<key>", key)
    if template:
        return name, f"{template} {key}".strip()
    return name, key


def speech_to_say(raw: object) -> str:
    """Plain spoken text. Not executed, and not longer than the spoken cap."""
    if not isinstance(raw, str):
        raise KikoError("speech was not text")
    text = " ".join(_CONTROL.sub(" ", raw).split())
    words = text.split(" ")
    if len(words) > SPEECH_WORD_CAP:
        text = " ".join(words[:SPEECH_WORD_CAP])
    if len(text) > SPEECH_CHAR_CAP:
        cut = text[:SPEECH_CHAR_CAP]
        text = (cut.rsplit(" ", 1)[0] or cut).strip()
    if not text:
        raise KikoError("empty speech")
    return text


def _with_job_id(url: str, job_id: str) -> str:
    parts = urlsplit(url)
    query = dict(parse_qsl(parts.query, keep_blank_values=True))
    query["job_id"] = job_id
    return urlunsplit((parts.scheme, parts.netloc, parts.path, urlencode(query), parts.fragment))


class KikoClient:
    def __init__(self, webhook_url: str, webhook_key: str, result_url: str, result_key: str,
                 webhook_auth_header: str = "Authorization: Bearer <key>",
                 result_auth_header: str = "Authorization: Bearer <key>",
                 timeout_s: float = 180.0, poll_s: float = POLL_INTERVAL_S,
                 transport: httpx.AsyncBaseTransport | None = None,
                 sleep=asyncio.sleep, clock=time.monotonic) -> None:
        self._webhook_url = webhook_url.strip()
        self._webhook_key = webhook_key
        self._webhook_auth = webhook_auth_header
        self._result_url = result_url.strip()
        self._result_key = result_key
        self._result_auth = result_auth_header
        self._timeout_s = timeout_s
        self._poll_s = poll_s
        self._sleep = sleep
        self._clock = clock
        self._client = httpx.AsyncClient(transport=transport, timeout=httpx.Timeout(20.0, connect=5.0))

    async def ask(self, request: str) -> str:
        text = " ".join((request or "").split())
        if not text:
            raise KikoError("empty request")
        if not self._webhook_url or not self._result_url:
            raise KikoError("kiko not configured")
        if not self._webhook_key or not self._result_key:
            raise KikoError("kiko keys not configured")
        job_id = str(uuid.uuid4())
        deadline = self._clock() + self._timeout_s
        await self._submit(job_id, text)
        while True:
            found = await self._poll(job_id)
            if found is not None:
                return speech_to_say(found)
            if self._clock() >= deadline:
                raise KikoTimeout("timed out waiting for Kiko")
            await self._sleep(min(self._poll_s, max(0.0, deadline - self._clock())))

    async def _submit(self, job_id: str, text: str) -> None:
        name, value = authorization_header(self._webhook_auth, self._webhook_key)
        body = {"job_id": job_id, "text": text, "from": "reachy", "reply_to": self._result_url}
        try:
            response = await self._client.post(self._webhook_url, json=body, headers={name: value})
            response.raise_for_status()
        except KikoError:
            raise
        except Exception as exc:  # noqa: BLE001 - httpx errors and bad URLs become a spoken fallback
            raise KikoError(self._http_error("webhook", exc)) from exc

    async def _poll(self, job_id: str) -> str | None:
        name, value = authorization_header(self._result_auth, self._result_key)
        url = _with_job_id(self._result_url, job_id)
        try:
            response = await self._client.get(url, headers={name: value})
        except Exception as exc:  # noqa: BLE001 - a blip while polling should wait, not end the ask
            if self._fatal_transport(exc):
                raise KikoError(self._http_error("result", exc)) from exc
            return None
        if response.status_code in (401, 403):
            raise KikoError(f"result mailbox rejected the key ({response.status_code})")
        if response.status_code == 404:
            return None
        if response.status_code >= 500:
            return None
        if response.status_code >= 400:
            raise KikoError(f"result mailbox rejected the poll ({response.status_code})")
        try:
            payload = response.json()
        except Exception as exc:  # noqa: BLE001
            raise KikoError("result mailbox did not return JSON") from exc
        if not isinstance(payload, dict):
            raise KikoError("result mailbox did not return JSON")
        if payload.get("pending") is True and "speech" not in payload:
            return None
        speech = payload.get("speech")
        if speech is None:
            return None
        if not isinstance(speech, str):
            raise KikoError("speech was not text")
        return speech

    @staticmethod
    def _fatal_transport(exc: Exception) -> bool:
        return isinstance(exc, (httpx.InvalidURL, httpx.UnsupportedProtocol))

    @staticmethod
    def _http_error(where: str, exc: Exception) -> str:
        status = getattr(getattr(exc, "response", None), "status_code", None)
        if status is not None:
            return f"{where} rejected the call ({status})"
        return f"{where} {type(exc).__name__}"

    async def aclose(self) -> None:
        await self._client.aclose()
