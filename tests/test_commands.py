import pytest
import yaml  # type: ignore[import-untyped]

from tars.voice.commands import apply, parse, words_to_number


@pytest.mark.parametrize(
    "text,expected",
    [
        ("Humor 40%.", ("humor", 40)),
        ("TARS, set your humor setting to forty percent", ("humor", 40)),
        ("humour to seventy-five", ("humor", 75)),
        ("Honesty setting 90 percent", ("honesty", 90)),
        ("set honesty to a hundred", ("honesty", 100)),
        ("Verbosity high please", ("verbosity", "high")),
    ],
)
def test_parses_settings(text, expected):
    assert parse(text) == expected


@pytest.mark.parametrize(
    "text",
    ["what's your humor setting?", "tell me something funny", "humor 150%", "I like honesty"],
)
def test_ignores_questions_and_out_of_range(text):
    assert parse(text) is None


@pytest.mark.parametrize("w,n", [("40", 40), ("forty five", 45), ("zero", 0), ("a hundred", 100)])
def test_words_to_number(w, n):
    assert words_to_number(w) == n


def test_apply_updates_and_persists(tmp_path):
    cfg = {"personality": {"humor": 60}}
    user = tmp_path / "tars.yaml"
    user.write_text("user_name: Ekansh\n")
    assert apply(cfg, "humor", 40, user) == "Humor setting 40 percent."
    assert cfg["personality"]["humor"] == 40
    saved = yaml.safe_load(user.read_text())
    assert saved == {"user_name": "Ekansh", "personality": {"humor": 40}}
