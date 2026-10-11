import pytest

from reachy_voice.config import load_settings

KEYS = {"GEMINI_API_KEY": "g", "OPENAI_API_KEY": "o"}


def test_defaults_with_both_keys():
    s = load_settings(KEYS)
    assert s.engine == "alternate"
    assert s.gemini_model == "gemini-3.8-live" and s.openai_model == "gpt-live-1"
    assert s.wake_model == "hey_jarvis" and s.wake_threshold == 0.5
    assert s.speech_threshold == 0.015
    assert (s.idle_timeout_s, s.pending_max_s, s.max_session_s) == (30.0, 330.0, 600.0)
    assert (s.quick_model, s.quick_provider) == ("gpt-5.4-nano", "openai-api")


def test_overrides_from_env():
    s = load_settings({**KEYS, "VOICE_ENGINE": " OpenAI ", "SPEECH_THRESHOLD": "0.02", "IDLE_TIMEOUT_S": "45",
                       "HOME_AGENT_URL": "http://pi:8642/", "HOME_AGENT_KEY": "k"})
    assert s.engine == "openai" and s.speech_threshold == 0.02 and s.idle_timeout_s == 45.0
    assert s.home_agent_url == "http://pi:8642/" and s.home_agent_key == "k"


def test_bad_engine_is_rejected():
    with pytest.raises(ValueError, match="VOICE_ENGINE"):
        load_settings({**KEYS, "VOICE_ENGINE": "alexa"})


def test_missing_key_for_chosen_engine_is_rejected():
    with pytest.raises(ValueError, match="OPENAI_API_KEY"):
        load_settings({"GEMINI_API_KEY": "g", "VOICE_ENGINE": "alternate"})
    assert load_settings({"GEMINI_API_KEY": "g", "VOICE_ENGINE": "gemini"}).engine == "gemini"


def test_has_engine_reflects_keys():
    s = load_settings({"GEMINI_API_KEY": "g", "VOICE_ENGINE": "gemini"})
    assert s.has_engine("gemini") and not s.has_engine("openai")


def test_repr_does_not_leak_keys():
    s = load_settings({"GEMINI_API_KEY": "gem-secret", "OPENAI_API_KEY": "oai-secret", "HOME_AGENT_KEY": "home-secret"})
    text = repr(s)
    assert "gem-secret" not in text and "oai-secret" not in text and "home-secret" not in text


def test_body_settings_defaults_and_overrides():
    s = load_settings(KEYS)
    assert (s.body_enabled, s.idle_awake_s, s.expression_min_gap_s, s.tracking_weight) == (True, 300.0, 8.0, 0.6)
    s = load_settings({**KEYS, "BODY_ENABLED": "false", "IDLE_AWAKE_S": "60", "TRACKING_WEIGHT": "0.4"})
    assert (s.body_enabled, s.idle_awake_s, s.tracking_weight) == (False, 60.0, 0.4)
    assert load_settings({**KEYS, "BODY_ENABLED": "1"}).body_enabled is True


def test_bad_body_flag_is_rejected():
    with pytest.raises(ValueError, match="BODY_ENABLED"):
        load_settings({**KEYS, "BODY_ENABLED": "maybe"})
