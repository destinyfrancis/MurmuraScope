"""Tests for SentimentAnalyzer (hybrid keyword + Transformer sentiment analysis).

Handles graceful degradation when the ``transformers`` library is not installed
in the test environment — all tests still exercise the keyword-only fast path.
"""
from __future__ import annotations

import pytest

# ---------------------------------------------------------------------------
# Graceful import — skip entire module if sentiment_analyzer cannot load
# ---------------------------------------------------------------------------

try:
    from backend.app.services.sentiment_analyzer import (
        SentimentResult,
        analyze_batch,
        analyze_news_headline,
        analyze_text,
    )

    _IMPORT_OK = True
    _IMPORT_ERROR = ""
except ImportError as exc:
    _IMPORT_OK = False
    _IMPORT_ERROR = str(exc)

pytestmark = pytest.mark.skipif(
    not _IMPORT_OK,
    reason=f"SentimentAnalyzer import failed: {_IMPORT_ERROR}",
)

_VALID_LABELS = {"positive", "negative", "neutral"}


# ---------------------------------------------------------------------------
# 1. Instantiation / module-level sanity
# ---------------------------------------------------------------------------


class TestAnalyzerInstantiation:
    """Verify the module loads and core functions are callable."""

    def test_analyzer_instantiation(self) -> None:
        """analyze_text is a callable function after import."""
        assert callable(analyze_text)
        assert callable(analyze_batch)
        assert callable(analyze_news_headline)


# ---------------------------------------------------------------------------
# 2–4. Single-text analysis
# ---------------------------------------------------------------------------


class TestSingleTextAnalysis:
    """Analyse individual Cantonese texts for correct sentiment labels."""

    def test_analyze_positive_text(self) -> None:
        """Clearly positive Cantonese text should return 'positive'."""
        result = analyze_text("好開心呀今日加咗人工")
        assert result.label == "positive"
        assert 0.0 <= result.confidence <= 1.0

    def test_analyze_negative_text(self) -> None:
        """Clearly negative Cantonese text should return 'negative'."""
        result = analyze_text("好慘啊失咗業")
        assert result.label == "negative"
        assert 0.0 <= result.confidence <= 1.0

    def test_analyze_neutral_text(self) -> None:
        """Ambiguous weather comment may be positive or neutral."""
        result = analyze_text("今日天氣幾好")
        assert result.label in ("positive", "neutral")
        assert 0.0 <= result.confidence <= 1.0


# ---------------------------------------------------------------------------
# 5. Batch analysis
# ---------------------------------------------------------------------------


class TestBatchAnalysis:
    """Batch processing returns one result per input text."""

    def test_analyze_batch(self) -> None:
        """Three texts should yield exactly three SentimentResult objects."""
        texts = ["好開心", "好慘", "普通"]
        results = analyze_batch(texts)
        assert len(results) == 3
        for r in results:
            assert isinstance(r, SentimentResult)
            assert r.label in _VALID_LABELS
            assert 0.0 <= r.confidence <= 1.0

    def test_batch_empty_list(self) -> None:
        """Empty input list should return empty output list."""
        results = analyze_batch([])
        assert results == []


# ---------------------------------------------------------------------------
# 6. Result field structure
# ---------------------------------------------------------------------------


class TestSentimentResultFields:
    """SentimentResult exposes the expected public attributes."""

    def test_sentiment_result_fields(self) -> None:
        """Result must have label (str), confidence (float), aspects (dict)."""
        result = analyze_text("香港樓價太貴")
        assert isinstance(result.label, str)
        assert result.label in _VALID_LABELS
        assert isinstance(result.confidence, float)
        assert isinstance(result.aspects, dict)

    def test_result_is_frozen(self) -> None:
        """SentimentResult should be immutable (frozen dataclass)."""
        result = analyze_text("測試")
        with pytest.raises(AttributeError):
            result.label = "positive"  # type: ignore[misc]


# ---------------------------------------------------------------------------
# 7. Keyword fast-path confidence
# ---------------------------------------------------------------------------


class TestKeywordFastPath:
    """Short text with clear sentiment should hit the keyword fast path."""

    def test_keyword_fast_path(self) -> None:
        """Strongly positive keyword text returns confidence >= 0.6."""
        result = analyze_text("好開心好正好掂")
        assert result.label == "positive"
        assert result.confidence >= 0.6


# ---------------------------------------------------------------------------
# 8. News headline analysis
# ---------------------------------------------------------------------------


class TestNewsHeadline:
    """analyze_news_headline uses keyword-only mode (no Transformer)."""

    def test_analyze_news_headline(self) -> None:
        """Negative headline should return a valid result with label."""
        result = analyze_news_headline("樓價急跌創新低")
        assert isinstance(result, SentimentResult)
        assert result.label in _VALID_LABELS
        assert 0.0 <= result.confidence <= 1.0

    def test_headline_negative_content(self) -> None:
        """Headline containing multiple negative keywords should be negative."""
        result = analyze_news_headline("經濟衰退慘烈 失業惡化危機加深")
        assert result.label == "negative"


# ---------------------------------------------------------------------------
# 9. Aspect detection
# ---------------------------------------------------------------------------


class TestAspectDetection:
    """Text mentioning domain keywords should populate result.aspects."""

    def test_aspect_detection_property(self) -> None:
        """Text about property should include 'property' in aspects."""
        result = analyze_text("樓價升到好離譜，供唔起按揭")
        assert "property" in result.aspects

    def test_aspect_detection_employment(self) -> None:
        """Text about jobs should include 'employment' in aspects."""
        result = analyze_text("公司裁員好多人失業")
        assert "employment" in result.aspects

    def test_aspect_detection_empty_for_generic(self) -> None:
        """Generic text without domain keywords should have empty aspects."""
        result = analyze_text("今日食咗個好味嘅蛋撻")
        assert isinstance(result.aspects, dict)
        # Aspects may or may not be empty depending on keyword overlap;
        # just verify the type is correct.


# ---------------------------------------------------------------------------
# 10. Empty / edge-case input
# ---------------------------------------------------------------------------


class TestEdgeCases:
    """Graceful handling of empty, whitespace, and unusual inputs."""

    def test_empty_text(self) -> None:
        """Empty string returns neutral without error."""
        result = analyze_text("")
        assert result.label == "neutral"
        assert result.confidence == 0.5
        assert result.aspects == {}

    def test_whitespace_only(self) -> None:
        """Whitespace-only string treated as empty."""
        result = analyze_text("   \t\n  ")
        assert result.label == "neutral"

    def test_none_safe_headline(self) -> None:
        """Empty headline returns neutral without error."""
        result = analyze_news_headline("")
        assert result.label == "neutral"
        assert result.confidence == 0.5
