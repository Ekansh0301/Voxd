from tars.tools.documents import _chunks, index, search


def test_index_and_search(tmp_path):
    (tmp_path / "Documents/notes").mkdir(parents=True)
    (tmp_path / "Documents/notes/os.md").write_text(
        "Paging\n\nVirtual memory uses page tables and a TLB.\n"
    )
    (tmp_path / "Documents/.secret").mkdir()
    (tmp_path / "Documents/.secret/keys.txt").write_text("virtual private key")
    db = tmp_path / "docs.db"
    assert index(tmp_path, [tmp_path / "Documents"], db) == (1, 0)
    assert index(tmp_path, [tmp_path / "Documents"], db) == (0, 1)  # unchanged: not re-read
    hits = search("how does virtual memory work", db_path=db)
    assert hits and hits[0][0].endswith("os.md") and "[Virtual]" in hits[0][2]
    assert all(".secret" not in h[0] for h in hits)


def test_chunks_split_long_text():
    parts = _chunks("\n\n".join(f"para {i} " + "x" * 300 for i in range(10)))
    assert len(parts) > 2 and all(len(p) <= 1800 for p in parts)


def test_plain_speech_text():
    from tars.voice.text import _plain

    assert (
        _plain("- **Speed**: UDP is faster — TCP is `reliable`")
        == "Speed: UDP is faster, TCP is reliable"
    )
