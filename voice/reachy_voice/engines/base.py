"""The interface every voice engine implements, so the session doesn't care which runs."""

from collections.abc import Callable
from dataclasses import dataclass
from typing import Protocol

import numpy as np


@dataclass
class Delegation:
    call_id: str
    request: str
    lane: str  # "quick" | "task"


@dataclass
class EngineCallbacks:
    on_audio: Callable[[np.ndarray, float], None]   # float32 mono @16 kHz, monotonic now
    on_user_text: Callable[[str], None]
    on_robot_text: Callable[[str], None]
    on_interrupted: Callable[[float], None]
    on_delegation: Callable[[Delegation], None]
    on_usage: Callable[[dict], None]
    on_error: Callable[[str], None]


class VoiceEngine(Protocol):
    name: str

    async def start(self, cb: EngineCallbacks) -> None: ...
    async def send_audio(self, frame: np.ndarray) -> None: ...
    async def deliver(self, call_id: str, text: str) -> None: ...
    async def close(self) -> None: ...
    async def wait_closed(self) -> None: ...
