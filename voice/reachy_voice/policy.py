"""Small decisions: when a session ends, which engine runs next, which Hermes lane."""

import re
from dataclasses import dataclass

_QUICK = re.compile(r"\b(list|lists|note|notes|grocer\w*|shopping|what'?s on|add|remove)\b", re.IGNORECASE)


@dataclass(frozen=True)
class SessionPolicy:
    idle_timeout_s: float = 30.0
    pending_max_s: float = 330.0
    max_session_s: float = 600.0

    def should_close(self, now: float, opened_at: float, last_activity: float, pending_since: float | None) -> str | None:
        if now - opened_at >= self.max_session_s:
            return "max_duration"  # a TV left on must not hold the session open forever
        if pending_since is not None:
            return "pending_timeout" if now - pending_since >= self.pending_max_s else None
        if now - last_activity >= self.idle_timeout_s:
            return "idle"
        return None


def other_engine(name: str) -> str | None:
    """The bake-off partner for a failed start. Grok stays on Grok: a bad key must not
    silently speak with another engine."""
    return {"gemini": "openai", "openai": "gemini"}.get(name)


class EngineChooser:
    def __init__(self, mode: str) -> None:
        self._mode = mode
        self._next = "gemini"

    def next(self) -> str:
        if self._mode != "alternate":
            return self._mode
        name, self._next = self._next, other_engine(self._next)
        return name


def choose_lane(request: str) -> str:
    """Quick lane for household list/note lookups and edits; everything else is a task."""
    return "quick" if _QUICK.search(request or "") else "task"


# OpenAI has one delegation channel and no tool name. "what's on" is in the quick
# regex, so a calendar question has to be recognised before that rule.
_KIKO_WORK = re.compile(
    r"\b(calendar|schedule|scheduling|meeting|meetings|email|e-mail|inbox|research|message|messages|task|tasks)\b",
    re.IGNORECASE,
)
_LIST_WORK = re.compile(r"\b(list|lists|note|notes|grocer\w*|shopping)\b", re.IGNORECASE)


def route_delegation(request: str, *, kiko_enabled: bool) -> tuple[str, str]:
    """(lane, target) for a delegation that did not name a tool.

    Gemini and Grok name ask_home_agent or ask_kiko. OpenAI does not. Lists and
    notes stay with Hermes. Other delegated work goes to Kiko when configured.
    """
    if not kiko_enabled:
        return choose_lane(request), "hermes"
    text = request or ""
    if _KIKO_WORK.search(text):
        return "kiko", "kiko"
    if _LIST_WORK.search(text) or choose_lane(text) == "quick":
        return "quick", "hermes"
    return "kiko", "kiko"
