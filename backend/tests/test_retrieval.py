"""BM25, RRF fusion, hybrid retrieval and reranking."""

from __future__ import annotations

import pytest

from app.core.exceptions import RerankerUnavailable, VectorDimensionMismatch
from app.rag.bm25_retriever import BM25Index
from app.rag.hybrid_retriever import Candidate, HybridRetriever, reciprocal_rank_fusion
from app.rag.reranker import CrossEncoderReranker
from app.rag.vector_store import DenseHit, VectorPoint, VectorStore, build_qdrant_client
from tests.conftest import DIM, FakeEmbedder, OverlapScorer, make_settings


def payload(doc: str, idx: int, text: str) -> dict:
    return {
        "document_id": doc,
        "filename": f"{doc}.md",
        "chunk_index": idx,
        "page_number": None,
        "content": text,
    }


CORPUS = [
    ("c1", "d1", "Qdrant stores dense vectors and supports cosine similarity search."),
    (
        "c2",
        "d1",
        "BM25 is a lexical ranking function using term frequency and inverse document frequency.",
    ),
    ("c3", "d2", "Reciprocal rank fusion merges ranked lists using one over k plus rank."),
    ("c4", "d2", "Cross encoders score query and passage pairs jointly for reranking."),
]


@pytest.fixture
def bm25() -> BM25Index:
    idx = BM25Index()
    idx.add_many([(cid, text, payload(doc, i, text)) for i, (cid, doc, text) in enumerate(CORPUS)])
    return idx


# ---------------------------------------------------------------------- BM25


def test_bm25_ranks_relevant_chunk_first(bm25):
    hits = bm25.search("lexical term frequency ranking", limit=3)
    assert hits[0].chunk_id == "c2"
    assert hits[0].score > 0


def test_bm25_empty_index_and_empty_query():
    assert BM25Index().search("anything", 5) == []
    idx = BM25Index()
    idx.add("x", "some text", payload("d", 0, "some text"))
    assert idx.search("the of and", 5) == []  # only stopwords


def test_bm25_document_filter(bm25):
    hits = bm25.search("rank fusion reranking", limit=5, document_ids=["d1"])
    assert hits == [] or all(h.payload["document_id"] == "d1" for h in hits)


def test_bm25_remove_document_keeps_index_in_sync(bm25):
    assert bm25.remove_document("d2") == 2
    assert bm25.size == 2
    assert bm25.search("reciprocal rank fusion", 5) == []
    assert "d2" not in bm25.document_ids()
    assert "fusion" not in bm25._postings


def test_bm25_re_adding_chunk_replaces_it(bm25):
    bm25.add("c1", "completely different words now", payload("d1", 0, "x"))
    assert bm25.size == 4
    assert all(h.chunk_id != "c1" for h in bm25.search("cosine similarity", 5))


def test_bm25_scores_positive_in_tiny_corpus():
    idx = BM25Index()
    idx.add("only", "unique solitary passage", payload("d", 0, "unique solitary passage"))
    hits = idx.search("solitary", 5)
    assert hits and hits[0].score > 0


# ---------------------------------------------------------------------- RRF


def dense(*ids: str) -> list[DenseHit]:
    return [
        DenseHit(chunk_id=i, score=1.0 - n * 0.1, payload=payload("d", n, i))
        for n, i in enumerate(ids)
    ]


def lex(*ids: str) -> list[tuple[str, float, dict]]:
    return [(i, 10.0 - n, payload("d", n, i)) for n, i in enumerate(ids)]


def test_rrf_rewards_agreement_between_retrievers():
    fused = reciprocal_rank_fusion(dense("a", "b", "c"), lex("c", "b", "d"), k=60)
    ids = [c.chunk_id for c in fused]
    # b is #2 in both lists -> beats a (#1 dense only) and d (#3 lexical only).
    assert ids.index("b") < ids.index("a")
    assert ids.index("c") < ids.index("d")
    b = next(c for c in fused if c.chunk_id == "b")
    assert b.fused_score == pytest.approx(1 / 62 + 1 / 62)
    assert b.dense_rank == 2 and b.bm25_rank == 2


def test_rrf_deduplicates_by_chunk_id():
    fused = reciprocal_rank_fusion(dense("a", "a", "b"), lex("a", "b", "b"), k=60)
    assert sorted(c.chunk_id for c in fused) == ["a", "b"]
    a = next(c for c in fused if c.chunk_id == "a")
    assert a.dense_rank == 1 and a.bm25_rank == 1  # duplicates ignored


def test_rrf_weights_and_limit():
    fused = reciprocal_rank_fusion(
        dense("a"), lex("b"), k=60, dense_weight=0.0, bm25_weight=1.0, limit=1
    )
    assert [c.chunk_id for c in fused] == ["b"]


def test_rrf_handles_empty_inputs():
    assert reciprocal_rank_fusion([], []) == []
    only_dense = reciprocal_rank_fusion(dense("x"), [])
    assert only_dense[0].bm25_rank is None and only_dense[0].dense_rank == 1


# ---------------------------------------------------------------------- vector store + hybrid


@pytest.fixture
async def store(tmp_path):
    settings = make_settings(tmp_path)
    vs = VectorStore(build_qdrant_client(settings), "hybrid_test", DIM)
    await vs.initialize()
    yield vs
    await vs.close()


async def index_corpus(store: VectorStore, bm25: BM25Index, embedder: FakeEmbedder) -> None:
    import uuid

    vectors = await embedder.embed_documents([t for _, _, t in CORPUS])
    points = []
    for (cid, doc, text), vec in zip(CORPUS, vectors, strict=True):
        pid = str(uuid.uuid5(uuid.NAMESPACE_URL, cid))
        points.append(
            VectorPoint(id=pid, vector=vec, payload=payload(doc, 0, text) | {"chunk_id": pid})
        )
    await store.upsert(points)
    bm25.clear()
    bm25.add_many([(p.id, p.payload["content"], p.payload) for p in points])


async def test_empty_collection_returns_no_results(store):
    retriever = HybridRetriever(FakeEmbedder(), store, BM25Index())
    result = await retriever.retrieve("anything at all", top_k=5)
    assert result.candidates == [] and result.dense_count == 0 and result.bm25_count == 0


async def test_hybrid_retrieves_relevant_chunk(store, embedder):
    bm25 = BM25Index()
    await index_corpus(store, bm25, embedder)
    retriever = HybridRetriever(embedder, store, bm25)
    result = await retriever.retrieve("how does reciprocal rank fusion merge lists", top_k=4)
    assert result.candidates[0].content.startswith("Reciprocal rank fusion")
    top = result.candidates[0]
    assert top.dense_rank is not None and top.bm25_rank is not None
    assert len({c.chunk_id for c in result.candidates}) == len(result.candidates)


async def test_vector_store_document_filter_and_delete(store, embedder):
    bm25 = BM25Index()
    await index_corpus(store, bm25, embedder)
    vec = await embedder.embed_query("vectors")
    only_d2 = await store.search(vec, limit=10, document_ids=["d2"])
    assert only_d2 and all(h.payload["document_id"] == "d2" for h in only_d2)
    await store.delete_document("d2")
    assert await store.count() == 2
    assert await store.count("d2") == 0


async def test_dimension_mismatch_detected(tmp_path):
    settings = make_settings(tmp_path)
    client = build_qdrant_client(settings)
    first = VectorStore(client, "dims", 8)
    await first.initialize()
    second = VectorStore(client, "dims", 16)  # e.g. embedding model changed
    await second.initialize()
    assert second.dimension_error and "reindex" in second.dimension_error
    with pytest.raises(VectorDimensionMismatch):
        await second.search([0.0] * 16, limit=1)
    health = await second.health()
    assert health[0] == "degraded"


async def test_upsert_rejects_wrong_vector_size(store):
    with pytest.raises(VectorDimensionMismatch):
        await store.upsert(
            [VectorPoint(id="00000000-0000-0000-0000-000000000001", vector=[0.1] * 3, payload={})]
        )


# ---------------------------------------------------------------------- reranking


def cands(*texts: str) -> list[Candidate]:
    return [
        Candidate(chunk_id=f"c{i}", payload=payload("d", i, t), fused_score=1 / (60 + i))
        for i, t in enumerate(texts)
    ]


def test_reranker_orders_by_score_and_truncates():
    scorer = OverlapScorer()
    rr = CrossEncoderReranker("fake", scorer=scorer)
    out = rr.rerank_sync(
        "python packaging tools",
        cands("cooking pasta", "python packaging with tools", "python"),
        top_n=2,
    )
    assert out.mode == "cross_encoder" and out.applied
    assert [c.content for c in out.candidates] == ["python packaging with tools", "python"]
    assert out.candidates[0].rerank_score > out.candidates[1].rerank_score
    # Metadata preserved through reranking.
    assert out.candidates[0].payload["filename"] == "d.md"


def test_reranker_min_score_filters():
    rr = CrossEncoderReranker("fake", scorer=OverlapScorer(), min_score=0.5)
    out = rr.rerank_sync("alpha beta", cands("gamma", "alpha beta"), top_n=5)
    assert [c.content for c in out.candidates] == ["alpha beta"]


def test_reranker_disabled_keeps_fusion_order():
    rr = CrossEncoderReranker("fake", enabled=False)
    out = rr.rerank_sync("q", cands("a", "b", "c"), top_n=2)
    assert out.mode == "disabled" and not out.applied
    assert [c.chunk_id for c in out.candidates] == ["c0", "c1"]


def test_reranker_load_failure_errors_by_default(monkeypatch):
    rr = CrossEncoderReranker("does/not-exist", fallback="error")

    def fail(*_a, **_k):
        raise OSError("model download failed")

    monkeypatch.setattr("app.rag.reranker.SentenceTransformerScorer", fail)
    with pytest.raises(RerankerUnavailable, match="model download failed"):
        rr.rerank_sync("q", cands("a"), top_n=1)
    assert rr.state == "failed"


def test_reranker_load_failure_explicit_fusion_fallback(monkeypatch):
    rr = CrossEncoderReranker("does/not-exist", fallback="fusion")

    def fail(*_a, **_k):
        raise OSError("x")

    monkeypatch.setattr("app.rag.reranker.SentenceTransformerScorer", fail)
    out = rr.rerank_sync("q", cands("a", "b"), top_n=1)
    assert out.mode == "fallback_fusion" and not out.applied
    assert out.candidates[0].rerank_score is None


def test_reranker_inference_failure_handled():
    class Broken:
        def predict(self, pairs):
            raise RuntimeError("CUDA OOM")

    with pytest.raises(RerankerUnavailable, match="inference failed"):
        CrossEncoderReranker("fake", scorer=Broken()).rerank_sync("q", cands("a"), 1)
    out = CrossEncoderReranker("fake", scorer=Broken(), fallback="fusion").rerank_sync(
        "q", cands("a"), 1
    )
    assert out.mode == "fallback_fusion"


def test_reranker_model_loaded_once(monkeypatch):
    loads = []

    class Counting(OverlapScorer):
        def __init__(self, *_a, **_k):
            super().__init__()
            loads.append(1)

    monkeypatch.setattr("app.rag.reranker.SentenceTransformerScorer", Counting)
    rr = CrossEncoderReranker("m")
    for _ in range(5):
        rr.rerank_sync("q", cands("a", "b"), 1)
    assert len(loads) == 1 and rr.state == "loaded"


def test_reranker_empty_candidates():
    out = CrossEncoderReranker("fake", scorer=OverlapScorer()).rerank_sync("q", [], 3)
    assert out.candidates == []


@pytest.mark.slow
def test_real_cross_encoder_ranks_relevant_passage_first():
    """Downloads cross-encoder/ms-marco-MiniLM-L-6-v2 (~90 MB) on first run."""
    rr = CrossEncoderReranker("cross-encoder/ms-marco-MiniLM-L-6-v2")
    out = rr.rerank_sync(
        "What is the capital of France?",
        cands(
            "Bananas are a good source of potassium.",
            "Paris is the capital and largest city of France.",
            "The Eiffel tower is tall.",
        ),
        top_n=3,
    )
    assert out.mode == "cross_encoder"
    assert out.candidates[0].content.startswith("Paris")
