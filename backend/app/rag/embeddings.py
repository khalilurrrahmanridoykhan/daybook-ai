"""Pluggable embedding backends. Default is Ollama's real embeddings API
(nomic-embed-text) -- genuine dense semantic embeddings, self-hosted, no
cloud provider involved. LocalHashingEmbedder is the offline fallback
(USE_LOCAL_EMBEDDER=true) so the RAG pipeline stays fully testable with
no live Ollama daemon, same "pluggable backend, smallest stack first"
pattern as the AMR Stewardship Briefing API's app/rag/embeddings.py.
"""

from __future__ import annotations

import hashlib
import math
import re

from app.rag.store import Embedder
from app.services import ollama_client

_TOKEN_RE = re.compile(r"[a-z0-9]+")


def _tokenize(text: str) -> list[str]:
    return _TOKEN_RE.findall(text.lower())


class OllamaEmbedder:
    def __init__(self, model: str | None = None) -> None:
        self.model = model

    def embed(self, texts: list[str]) -> list[list[float]]:
        return ollama_client.embed(texts, model=self.model)


class LocalHashingEmbedder:
    dims = 512

    def embed(self, texts: list[str]) -> list[list[float]]:
        return [self._embed_one(t) for t in texts]

    def _embed_one(self, text: str) -> list[float]:
        vec = [0.0] * self.dims
        for token in _tokenize(text):
            digest = int(hashlib.sha1(token.encode()).hexdigest(), 16)
            idx = digest % self.dims
            sign = 1.0 if (digest // self.dims) % 2 == 0 else -1.0
            vec[idx] += sign
        norm = math.sqrt(sum(v * v for v in vec)) or 1.0
        return [v / norm for v in vec]


def get_default_embedder() -> Embedder:
    from app.config import settings

    if settings.use_local_embedder:
        return LocalHashingEmbedder()
    return OllamaEmbedder(model=settings.ollama_embedding_model)
