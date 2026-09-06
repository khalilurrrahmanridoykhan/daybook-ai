from app.rag.embeddings import LocalHashingEmbedder
from app.rag.store import Document, InMemoryVectorStore


def _store() -> InMemoryVectorStore:
    store = InMemoryVectorStore(embedder=LocalHashingEmbedder())
    store.add(
        [
            Document(id="ridoy-doc", source_type="knowledge", title="about-ridoy", text="Ridoy is a senior full-stack developer specializing in public health informatics and DHIS2."),
            Document(id="ewars-doc", source_type="knowledge", title="projects", text="Bangladesh EWARS is a disease surveillance platform for outbreak monitoring."),
            Document(id="tools-doc", source_type="knowledge", title="tools", text="The assistant can calculate arithmetic expressions and get the current date and time."),
        ]
    )
    return store


def test_search_on_empty_store_returns_empty_list():
    store = InMemoryVectorStore(embedder=LocalHashingEmbedder())
    assert store.search("anything", k=3) == []


def test_search_ranks_lexically_closest_document_first():
    store = _store()
    results = store.search("What does Ridoy specialize in, public health informatics?", k=1)
    assert results[0].document.id == "ridoy-doc"


def test_search_respects_k():
    store = _store()
    assert len(store.search("developer surveillance calculate", k=2)) == 2


def test_embedder_is_deterministic_and_normalized():
    embedder = LocalHashingEmbedder()
    [v1] = embedder.embed(["disease surveillance platform"])
    [v2] = embedder.embed(["disease surveillance platform"])
    assert v1 == v2
    assert abs(sum(x * x for x in v1) - 1.0) < 1e-9
