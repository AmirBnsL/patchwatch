"""Normalization + content hashing."""

from patchwatch.ingest.normalize import content_hash, normalize_text


def test_normalize_collapses_whitespace() -> None:
    assert normalize_text("a\n\n b \t c  ") == "a b c"
    assert normalize_text("") == ""


def test_content_hash_ignores_whitespace_differences() -> None:
    assert content_hash("same text") == content_hash("  same \n text \t")


def test_content_hash_sensitive_to_words() -> None:
    assert content_hash("same text") != content_hash("different text")
