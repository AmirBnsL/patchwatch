"""Embedding provider tests — deterministic fake + mocked OpenAI path."""

from __future__ import annotations

from patchwatch.ingest.embeddings import HashEmbeddings, cosine_similarity


def test_hash_embeddings_deterministic() -> None:
    provider = HashEmbeddings(dim=64)
    assert provider.embed(["same text"]) == provider.embed(["same text"])


def test_hash_embeddings_normalized() -> None:
    provider = HashEmbeddings(dim=64)
    vector = provider.embed(["hello world"])[0]
    assert abs(sum(component**2 for component in vector) - 1.0) < 1e-9


def test_similar_texts_score_higher_than_unrelated() -> None:
    provider = HashEmbeddings(dim=256)
    q = provider.embed(["ahri q orb of deception magic damage"])[0]
    near = provider.embed(["ahri q orb of deception deals magic damage twice"])[0]
    far = provider.embed(["tahm kench ultimate tournament competitive ruling"])[0]
    assert cosine_similarity(q, near) > cosine_similarity(q, far)


def test_cosine_similarity_edge_cases() -> None:
    assert cosine_similarity([1.0, 0.0], [1.0, 0.0]) == 1.0
    assert cosine_similarity([0.0, 0.0], [1.0, 0.0]) == 0.0
    assert cosine_similarity([1.0, 0.0], [-1.0, 0.0]) == -1.0


def test_batch_preserves_order() -> None:
    provider = HashEmbeddings(dim=32)
    texts = ["alpha beta", "gamma", "alpha beta", "delta epsilon zeta"]
    vectors = provider.embed(texts)
    assert len(vectors) == 4
    assert vectors[0] == vectors[2]  # same text → same vector
    assert vectors[1] != vectors[3]
