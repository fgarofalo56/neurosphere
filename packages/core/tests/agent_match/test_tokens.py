from __future__ import annotations

from neurosphere_core.recommendations.matching import normalize_tokens


def test_lowercase_split_stopwords_dedupe_order() -> None:
    assert normalize_tokens("Summarize the PDF, and the pdf of Invoices!") == (
        "summarize",
        "pdf",
        "invoices",
    )


def test_cap_defaults_to_32_and_is_adjustable() -> None:
    text = " ".join(f"w{i}" for i in range(100))
    assert len(normalize_tokens(text)) == 32
    assert normalize_tokens(text, limit=3) == ("w0", "w1", "w2")


def test_empty_and_punctuation_only() -> None:
    assert normalize_tokens("") == ()
    assert normalize_tokens("  --- the ") == ()
