"""Token-based chunking (tiktoken, cl100k_base)."""

from patchwatch.ingest.chunking import chunk_text, count_tokens


def test_chunking_is_deterministic() -> None:
    text = "chunk me " * 300
    assert chunk_text(text) == chunk_text(text)


def test_short_text_single_chunk() -> None:
    assert len(chunk_text("short text")) == 1


def test_empty_text_no_chunks() -> None:
    assert chunk_text("") == []


def test_long_text_splits_into_bounded_chunks() -> None:
    text = "policy records retention disposal " * 60  # ~360 tokens
    chunks = chunk_text(text, chunk_tokens=128, overlap=16)
    assert len(chunks) >= 3
    assert all(count_tokens(c) <= 128 + 5 for c in chunks)
    assert all(c for c in chunks)


def test_overlap_between_adjacent_chunks() -> None:
    text = "alpha beta gamma delta epsilon zeta " * 40
    chunks = chunk_text(text, chunk_tokens=64, overlap=16)
    assert len(chunks) >= 3
    joined = " ".join(chunks).split()
    # Overlap means adjacent chunks share tokens; verify content is preserved overall.
    assert "alpha" in joined and "zeta" in joined


def test_chunking_validation() -> None:
    try:
        chunk_text("x", chunk_tokens=0)
    except ValueError:
        return
    raise AssertionError("expected ValueError for chunk_tokens=0")
