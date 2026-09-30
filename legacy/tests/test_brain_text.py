import pytest

from core.brain import Brain, QuickRouter, _format_for_speech


@pytest.fixture(scope="module")
def brain():
    # Skip __init__: it reads config and pings Ollama.
    return Brain.__new__(Brain)


@pytest.mark.parametrize(
    "text",
    [
        "Python is mostly written in C.",
        "It's sunny in New Delhi.",
        "I'm doing well, thanks for checking in.",
    ],
)
def test_clean_keeps_trailing_in_phrases(brain, text):
    assert brain._clean(text) == text


def test_clean_strips_filler_and_helper_tail(brain):
    out = brain._clean("Sure! The build passed. Is there anything else I can help with?")
    assert out == "The build passed."


def test_clean_drops_meta_commentary(brain):
    out = brain._clean("As an AI, I have no feelings. The file is saved.")
    assert out == "The file is saved."


@pytest.mark.parametrize(
    "text,action",
    [
        ("open youtube", "open_url"),
        ("open monkeytype.com", "open_url"),
        ("what's the weather", "get_weather"),
        ("what time is it", "get_time"),
        ("ask chatgpt to explain recursion", "open_url_and_type"),
    ],
)
def test_router_matches_high_confidence_intents(text, action):
    intent = QuickRouter().match(text)
    assert intent is not None and intent["action"] == action


def test_router_leaves_open_ended_requests_to_llm():
    assert QuickRouter().match("rename my screenshots from today by time") is None


def test_speech_format_shortens_urls_and_paths():
    out = _format_for_speech("Saved to /home/ekansh/notes.txt, see https://www.github.com/x/y")
    assert "~/notes.txt" in out and "github.com" in out and "https" not in out


def test_speech_format_converts_system_info():
    raw = "CPU 2.4% — RAM 6686/15623 MB (42.8%) — Disk 77/238 GB (32%) — Uptime 1h 2m"
    out = _format_for_speech(raw)
    assert out.startswith("CPU is at 2%") and "RAM is 6.5 of 15 GB used" in out
