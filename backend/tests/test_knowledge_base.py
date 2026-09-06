from app.rag.knowledge_base import _chunk, build_knowledge_store


def test_chunk_splits_on_blank_lines_and_respects_max_size():
    # Several short paragraphs that together exceed _MAX_CHUNK_CHARS (800) --
    # chunking only ever splits *between* paragraphs, never mid-paragraph.
    paragraphs = [f"Paragraph number {i} with some filler text to add up." for i in range(20)]
    text = "\n\n".join(paragraphs)
    docs = _chunk(text, source="test")
    assert len(docs) >= 2
    assert "".join(d.text for d in docs).replace("\n\n", " ") != ""
    assert docs[0].source_type == "knowledge"
    assert docs[0].title == "test"


def test_chunk_never_splits_a_single_paragraph_even_if_it_exceeds_the_cap():
    long_paragraph = "word " * 200  # ~1000 chars, no blank lines inside it
    docs = _chunk(long_paragraph, source="test")
    assert len(docs) == 1
    assert docs[0].text == long_paragraph.strip()


def test_chunk_empty_text_returns_no_documents():
    assert _chunk("", source="test") == []
    assert _chunk("\n\n\n", source="test") == []


def test_build_knowledge_store_loads_seed_files(monkeypatch, tmp_path):
    kb_dir = tmp_path / "knowledge"
    kb_dir.mkdir()
    (kb_dir / "one.md").write_text("This document is about Ridoy's DHIS2 work.", encoding="utf-8")
    (kb_dir / "two.md").write_text("This document is about self-hosted AI assistants.", encoding="utf-8")

    monkeypatch.setattr("app.rag.knowledge_base.settings.knowledge_base_dir", str(kb_dir))
    monkeypatch.setattr("app.rag.knowledge_base.settings.use_local_embedder", True)

    store = build_knowledge_store()
    results = store.search("self-hosted AI assistant", k=1)
    assert results[0].document.title == "two"
