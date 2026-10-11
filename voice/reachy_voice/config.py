"""Settings from the environment (on the robot: ~/reachy-voice/voice.env)."""

from collections.abc import Mapping
from dataclasses import dataclass, field

ENGINES = ("gemini", "openai", "alternate")


@dataclass(frozen=True)
class Settings:
    engine: str = "alternate"
    gemini_model: str = "gemini-3.8-live"
    gemini_voice: str = "Kore"
    openai_model: str = "gpt-live-1"
    openai_voice: str = "marin"
    wake_model: str = "hey_jarvis"
    wake_threshold: float = 0.5
    speech_threshold: float = 0.015
    idle_timeout_s: float = 30.0
    pending_max_s: float = 330.0
    max_session_s: float = 600.0
    home_agent_url: str = ""
    home_agent_key: str = field(default="", repr=False)
    quick_model: str = "gpt-5.4-nano"
    quick_provider: str = "openai-api"
    log_dir: str = "logs"
    gemini_api_key: str = field(default="", repr=False)
    openai_api_key: str = field(default="", repr=False)

    def has_engine(self, name: str) -> bool:
        return bool(self.gemini_api_key if name == "gemini" else self.openai_api_key if name == "openai" else False)


def load_settings(env: Mapping[str, str]) -> Settings:
    d = Settings()

    def text(name: str, default: str) -> str:
        value = env.get(name, "")
        return value.strip() if value and value.strip() else default

    def number(name: str, default: float) -> float:
        value = env.get(name, "")
        return float(value) if value and value.strip() else default

    s = Settings(
        engine=text("VOICE_ENGINE", d.engine).lower(),
        gemini_model=text("GEMINI_MODEL", d.gemini_model),
        gemini_voice=text("GEMINI_VOICE", d.gemini_voice),
        openai_model=text("OPENAI_LIVE_MODEL", d.openai_model),
        openai_voice=text("OPENAI_VOICE", d.openai_voice),
        wake_model=text("WAKE_MODEL", d.wake_model),
        wake_threshold=number("WAKE_THRESHOLD", d.wake_threshold),
        speech_threshold=number("SPEECH_THRESHOLD", d.speech_threshold),
        idle_timeout_s=number("IDLE_TIMEOUT_S", d.idle_timeout_s),
        pending_max_s=number("PENDING_MAX_S", d.pending_max_s),
        max_session_s=number("MAX_SESSION_S", d.max_session_s),
        home_agent_url=text("HOME_AGENT_URL", d.home_agent_url),
        home_agent_key=text("HOME_AGENT_KEY", d.home_agent_key),
        quick_model=text("QUICK_MODEL", d.quick_model),
        quick_provider=text("QUICK_PROVIDER", d.quick_provider),
        log_dir=text("VOICE_LOG_DIR", d.log_dir),
        gemini_api_key=text("GEMINI_API_KEY", ""),
        openai_api_key=text("OPENAI_API_KEY", ""),
    )
    if s.engine not in ENGINES:
        raise ValueError(f"VOICE_ENGINE must be one of {ENGINES}, got {s.engine!r}")
    needed = {"gemini": ["gemini"], "openai": ["openai"], "alternate": ["gemini", "openai"]}[s.engine]
    missing = [f"{n.upper()}_API_KEY" for n in needed if not s.has_engine(n)]
    if missing:
        raise ValueError(f"missing required settings: {', '.join(missing)}")
    return s
