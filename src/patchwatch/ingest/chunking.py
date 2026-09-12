"""Token-based chunking (tiktoken, ``cl100k_base``).

``cl100k_base`` is the encoder used by OpenAI ``text-embedding-3-small``, so
chunk boundaries here match the future embedding tokenization (Phase B).
"""

from __future__ import annotations

import tiktoken

ENCODER_NAME = "cl100k_base"
CHUNK_TOKENS = 256
CHUNK_OVERLAP = 32

_encoder = tiktoken.get_encoding(ENCODER_NAME)


def chunk_text(
    text: str, chunk_tokens: int = CHUNK_TOKENS, overlap: int = CHUNK_OVERLAP
) -> list[str]:
    """Split ``text`` into fixed-size token windows with overlap.

    The window slides by ``chunk_tokens - overlap`` tokens. Windows are decoded
    back to text, so a chunk may span ~``chunk_tokens`` tokens (rounding aside).
    Deterministic for a fixed encoder.
    """
    if chunk_tokens <= 0:
        raise ValueError("chunk_tokens must be > 0")
    if not 0 <= overlap < chunk_tokens:
        raise ValueError("overlap must be in [0, chunk_tokens)")

    tokens = _encoder.encode(text)
    if not tokens:
        return []

    step = chunk_tokens - overlap
    chunks: list[str] = []
    for start in range(0, len(tokens), step):
        window = tokens[start : start + chunk_tokens]
        chunks.append(_encoder.decode(window))
        if start + step >= len(tokens):
            break
    return chunks


def count_tokens(text: str) -> int:
    """Token count for ``text`` under the pinned encoder."""
    return len(_encoder.encode(text))
