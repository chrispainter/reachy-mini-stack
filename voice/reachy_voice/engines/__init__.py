"""Engine factory: one name per engine, built from Settings."""

from reachy_voice.config import Settings


def make_engine(name: str, settings: Settings):
    if name == "gemini":
        from reachy_voice.engines.gemini import GeminiLiveEngine

        return GeminiLiveEngine(settings.gemini_model, settings.gemini_voice, api_key=settings.gemini_api_key)
    if name == "openai":
        from reachy_voice.engines.openai_live import OpenAILiveEngine

        return OpenAILiveEngine(settings.openai_model, settings.openai_voice, api_key=settings.openai_api_key)
    raise ValueError(f"unknown engine {name!r}")
