"""Loads the RAG knowledge base from plain markdown/text files on disk,
chunked on blank-line paragraph breaks, embedded into an in-memory vector
store once per process. No ingestion pipeline: adding to this assistant's
knowledge is "drop a .md file in data/knowledge/ and restart," which is
the right amount of ceremony for a personal assistant's knowledge base at
this scale.
"""

from __future__ import annotations

from pathlib import Path

from app.config import settings
from app.rag.embeddings import get_default_embedder
from app.rag.store import Document, InMemoryVectorStore

_MAX_CHUNK_CHARS = 500

_store: InMemoryVectorStore | None = None


def _chunk(text: str, source: str) -> list[Document]:
    paragraphs = [p.strip() for p in text.split("\n\n") if p.strip()]
    docs: list[Document] = []
    buffer = ""
    idx = 0
    for para in paragraphs:
        if buffer and len(buffer) + len(para) > _MAX_CHUNK_CHARS:
            docs.append(Document(id=f"{source}-{idx}", source_type="knowledge", title=source, text=buffer))
            idx += 1
            buffer = ""
        buffer = f"{buffer}\n\n{para}" if buffer else para
    if buffer:
        docs.append(Document(id=f"{source}-{idx}", source_type="knowledge", title=source, text=buffer))
    return docs


def build_knowledge_store() -> InMemoryVectorStore:
    store = InMemoryVectorStore(embedder=get_default_embedder())
    kb_dir = Path(settings.knowledge_base_dir)
    docs: list[Document] = []
    if kb_dir.exists():
        for path in sorted(list(kb_dir.glob("*.md")) + list(kb_dir.glob("*.txt"))):
            docs.extend(_chunk(path.read_text(encoding="utf-8"), source=path.stem))
    store.add(docs)
    return store


def get_knowledge_store() -> InMemoryVectorStore:
    global _store
    if _store is None:
        _store = build_knowledge_store()
    return _store


def reset_knowledge_store() -> None:
    """Test/reload hook -- forces the next get_knowledge_store() call to
    rebuild from disk (e.g. after adding a new file)."""
    global _store
    _store = None
