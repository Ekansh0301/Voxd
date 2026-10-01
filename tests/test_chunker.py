import pytest

from tars.voice.chunker import SpeechChunker, clean_for_speech


def stream(text, step=3):
    c = SpeechChunker()
    out = []
    for i in range(0, len(text), step):
        out += c.feed(text[i : i + step])
    return out + c.flush()


def test_first_chunk_cuts_at_first_comma():
    out = stream("Sure thing, I checked your inbox. You have three new mails today.")
    assert out[0] == "Sure thing,"
    assert out[1:] == ["I checked your inbox.", "You have three new mails today."]


def test_first_chunk_needs_a_few_words():
    # a lone "Okay," is not spoken by itself; the clause is cut before "because"
    out = stream("Okay, so the build failed because pytest is missing.")
    assert out == ["Okay, so the build failed", "because pytest is missing."]


def test_later_commas_do_not_split():
    out = stream("Hello there, friend. Rahul wants the report, the slides, and the code by Friday.")
    # "friend." alone is too short to speak by itself, so it rides with the next sentence
    assert out == [
        "Hello there,",
        "friend. Rahul wants the report, the slides, and the code by Friday.",
    ]


def test_short_sentences_merge_with_the_next():
    out = stream("Right away, I will do that. Done. The file is saved in Downloads.")
    assert out == ["Right away,", "I will do that.", "Done. The file is saved in Downloads."]


def test_decimals_and_abbreviations_do_not_split():
    out = stream("Version 3.5 is out, e.g. on GitHub. It is faster than version two, they say.")
    assert out == [
        "Version 3.5 is out,",
        "e.g. on GitHub. It is faster than version two, they say.",
    ]


def test_nothing_spoken_until_a_break_arrives():
    c = SpeechChunker()
    assert c.feed("The quick brown fox jumps") == []
    assert c.flush() == ["The quick brown fox jumps"]


@pytest.mark.parametrize(
    "raw,spoken",
    [
        ("**Bold** and `code`", "Bold and code"),
        ("See https://www.github.com/x/y now", "See github.com now"),
        ("- first\n- second", "first second"),
        ("Saved to /home/ekansh/notes.txt", "Saved to home folder notes.txt"),
        ("```py\nprint(1)\n``` done", "code block done"),
    ],
)
def test_clean_for_speech(raw, spoken):
    assert clean_for_speech(raw) == spoken


def test_long_first_clause_cuts_before_a_joining_word():
    out = stream("I can't open Outlook or check your mail yet because I lack access to apps.")
    assert out == ["I can't open Outlook", "or check your mail yet because I lack access to apps."]


def test_long_first_clause_without_joiner_caps_at_ten_words():
    out = stream(
        "Python three point twelve brought faster startup better errors per interpreter GIL work today."
    )
    assert out[0] == "Python three point twelve brought faster startup better errors per"
    assert (
        " ".join(out).split()
        == (
            "Python three point twelve brought faster startup better errors per interpreter GIL work today."
        ).split()
    )
