"""Settings from the environment (on the robot: ~/reachy-voice/voice.env)."""

from collections.abc import Mapping
from dataclasses import dataclass, field

from reachy_voice.persona import load_persona

ENGINES = ("gemini", "openai", "grok", "alternate")
DEFAULT_KIKO_AUTH_HEADER = "Authorization: Bearer <key>"


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
    body_enabled: bool = True
    idle_awake_s: float = 300.0
    expression_min_gap_s: float = 8.0
    tracking_weight: float = 0.6
    gemini_api_key: str = field(default="", repr=False)
    openai_api_key: str = field(default="", repr=False)
    xai_model: str = "grok-voice-latest"
    xai_voice: str = "eve"
    xai_api_key: str = field(default="", repr=False)
    persona_name: str = "reachy"
    persona_file: str = ""
    kiko_webhook_url: str = ""
    kiko_webhook_key: str = field(default="", repr=False)
    kiko_webhook_auth_header: str = DEFAULT_KIKO_AUTH_HEADER
    kiko_result_url: str = ""
    kiko_result_key: str = field(default="", repr=False)
    kiko_result_auth_header: str = DEFAULT_KIKO_AUTH_HEADER
    kiko_timeout_s: float = 180.0
    kiko_max_words: int = 150

    def has_engine(self, name: str) -> bool:
        keys = {"gemini": self.gemini_api_key, "openai": self.openai_api_key, "grok": self.xai_api_key}
        return bool(keys.get(name, ""))

    @property
    def kiko_enabled(self) -> bool:
        """ask_kiko is offered only when both the webhook and the result mailbox are set."""
        return bool(self.kiko_webhook_url and self.kiko_result_url)


def load_settings(env: Mapping[str, str]) -> Settings:
    d = Settings()

    def text(name: str, default: str) -> str:
        value = env.get(name, "")
        return value.strip() if value and value.strip() else default

    def number(name: str, default: float) -> float:
        value = env.get(name, "")
        return float(value) if value and value.strip() else default

    def whole(name: str, default: int) -> int:
        value = (env.get(name) or "").strip()
        if not value:
            return default
        if not value.isdigit() or int(value) <= 0:
            raise ValueError(f"{name} must be a positive integer, got {value!r}")
        return int(value)

    def flag(name: str, default: bool) -> bool:
        value = (env.get(name) or "").strip().lower()
        if not value:
            return default
        if value in ("1", "true", "yes", "on"):
            return True
        if value in ("0", "false", "no", "off"):
            return False
        raise ValueError(f"{name} must be true or false, got {value!r}")

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
        body_enabled=flag("BODY_ENABLED", d.body_enabled),
        idle_awake_s=number("IDLE_AWAKE_S", d.idle_awake_s),
        expression_min_gap_s=number("EXPRESSION_MIN_GAP_S", d.expression_min_gap_s),
        tracking_weight=number("TRACKING_WEIGHT", d.tracking_weight),
        gemini_api_key=text("GEMINI_API_KEY", ""),
        openai_api_key=text("OPENAI_API_KEY", ""),
        xai_model=text("XAI_MODEL", d.xai_model),
        xai_voice=text("XAI_VOICE", d.xai_voice),
        xai_api_key=text("XAI_API_KEY", ""),
        persona_name=text("PERSONA_NAME", d.persona_name).lower(),
        persona_file=text("PERSONA_FILE", d.persona_file),
        kiko_webhook_url=text("KIKO_WEBHOOK_URL", d.kiko_webhook_url),
        kiko_webhook_key=text("KIKO_WEBHOOK_KEY", ""),
        kiko_webhook_auth_header=text("KIKO_WEBHOOK_AUTH_HEADER", d.kiko_webhook_auth_header),
        kiko_result_url=text("KIKO_RESULT_URL", d.kiko_result_url),
        kiko_result_key=text("KIKO_RESULT_KEY", ""),
        kiko_result_auth_header=text("KIKO_RESULT_AUTH_HEADER", d.kiko_result_auth_header),
        kiko_timeout_s=number("KIKO_TIMEOUT_S", d.kiko_timeout_s),
        kiko_max_words=whole("KIKO_MAX_WORDS", d.kiko_max_words),
    )
    if s.kiko_timeout_s <= 0:
        raise ValueError("KIKO_TIMEOUT_S must be positive")
    load_persona(s.persona_name, s.persona_file)
    if s.engine not in ENGINES:
        raise ValueError(f"VOICE_ENGINE must be one of {ENGINES}, got {s.engine!r}")
    key_env = {"gemini": "GEMINI_API_KEY", "openai": "OPENAI_API_KEY", "grok": "XAI_API_KEY"}
    needed = {"gemini": ["gemini"], "openai": ["openai"], "grok": ["grok"], "alternate": ["gemini", "openai"]}[s.engine]
    missing = [key_env[n] for n in needed if not s.has_engine(n)]
    if missing:
        raise ValueError(f"missing required settings: {', '.join(missing)}")
    return s
