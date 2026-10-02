from tars.privacy import redact, restore


def test_redacts_profile_and_patterns():
    profile = {"name": "Ekansh Goyal", "college": "IIIT Hyderabad"}
    text = "I'm Ekansh Goyal from IIIT Hyderabad, mail me at ekansh@example.com or call +91 98765 43210, roll 2021101234."
    out, mapping = redact(text, profile)
    for secret in ("Ekansh", "IIIT", "example.com", "98765", "2021101234"):
        assert secret not in out
    assert "[NAME]" in out and "[EMAIL1]" in out and "[PHONE1]" in out
    assert restore(out, mapping) == text


def test_plain_questions_untouched():
    out, mapping = redact("What is the capital of Japan?", {})
    assert out == "What is the capital of Japan?" and mapping == {}
