"""The smallest possible real vector store: embed the whole corpus once
at process start, then brute-force cosine similarity at query time. Fine
for a personal knowledge base's actual scale (dozens to a few hundred
chunks); a real ANN index (FAISS, pgvector) only earns its complexity
past that."""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Protocol


class Embedder(Protocol):
    def embed(self, texts: list[str]) -> list[list[float]]: ...


@dataclass(frozen=True)
class Document:
    id: str
    source_type: str
    title: str
    text: str


@dataclass(frozen=True)
class ScoredDocument:
    document: Document
    score: float


def _cosine(a: list[float], b: list[float]) -> float:
    dot = sum(x * y for x, y in zip(a, b))
    norm_a = math.sqrt(sum(x * x for x in a)) or 1.0
    norm_b = math.sqrt(sum(x * x for x in b)) or 1.0
    return dot / (norm_a * norm_b)


class InMemoryVectorStore:
    def __init__(self, embedder: Embedder) -> None:
        self._embedder = embedder
        self._docs: list[Document] = []
        self._vectors: list[list[float]] = []

    def add(self, documents: list[Document]) -> None:
        if not documents:
            return
        vectors = self._embedder.embed([d.text for d in documents])
        self._docs.extend(documents)
        self._vectors.extend(vectors)

    def search(self, query: str, k: int = 4) -> list[ScoredDocument]:
        if not self._docs:
            return []
        [query_vec] = self._embedder.embed([query])
        scored = [
            ScoredDocument(document=doc, score=_cosine(query_vec, vec))
            for doc, vec in zip(self._docs, self._vectors)
        ]
        scored.sort(key=lambda s: s.score, reverse=True)
        return scored[:k]
