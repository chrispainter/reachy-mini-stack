"""Engine factory: one name per engine, built from Settings."""

from reachy_voice.config import Settings
from reachy_voice.persona import load_persona


def _keyterms(settings: Settings, persona: str) -> list[str]:
    terms = ["Reachy", "Jarvis"]
    if settings.persona_name == "kiko" or "kiko" in persona.lower():
        terms.append("Kiko")
    return terms


def make_engine(name: str, settings: Settings):
    persona = load_persona(settings.persona_name, settings.persona_file)
    kiko = settings.kiko_enabled
    if name == "gemini":
        from reachy_voice.engines.gemini import GeminiLiveEngine

        return GeminiLiveEngine(settings.gemini_model, settings.gemini_voice, api_key=settings.gemini_api_key,
                                persona=persona, body_tools=settings.body_enabled, kiko_tool=kiko)
    if name == "openai":
        from reachy_voice.engines.openai_live import OpenAILiveEngine

        return OpenAILiveEngine(settings.openai_model, settings.openai_voice, api_key=settings.openai_api_key,
                                persona=persona, kiko_tool=kiko)
    if name == "grok":
        from reachy_voice.engines.grok import GrokLiveEngine

        return GrokLiveEngine(settings.xai_model, settings.xai_voice, api_key=settings.xai_api_key,
                              persona=persona, body_tools=settings.body_enabled, kiko_tool=kiko,
                              keyterms=_keyterms(settings, persona))
    raise ValueError(f"unknown engine {name!r}")
