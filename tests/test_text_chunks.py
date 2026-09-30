from tars.text_chunks import chunk_words


def _n(s):
    return len(s.split())


def test_short_text_is_one_chunk():
    assert chunk_words("One. Two three.", 190) == ["One. Two three."]


def test_chunks_respect_limit_and_keep_all_words_in_order():
    sent = "This sentence has exactly eight words in it."
    text = " ".join([sent] * 60)  # 480 words
    chunks = chunk_words(text, 190)
    assert all(_n(c) <= 190 for c in chunks)
    assert " ".join(chunks).split() == text.split()
    assert all(c.endswith(".") for c in chunks)  # cut at sentence boundaries


def test_paragraphs_are_preserved_within_chunks():
    text = "Para one is short.\n\nPara two is short too."
    assert chunk_words(text, 190) == [text]


def test_single_overlong_sentence_is_split():
    text = ("word " * 450).strip() + "."
    chunks = chunk_words(text, 190)
    assert all(_n(c) <= 190 for c in chunks) and len(chunks) == 3
    assert " ".join(chunks).split() == text.split()
