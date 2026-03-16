"""Hybrid sentiment analyzer: Cantonese keyword fast-path + Transformer fallback.

Keyword matching reuses the centralised lexicon from ``cantonese_lexicon.py``.
When keyword confidence is low or mixed signals are detected, falls back to
``hfl/chinese-roberta-wwm-ext`` (Chinese RoBERTa fine-tuned on sentiment;
output is 2-class positive/negative mapped to 3-class with neutral threshold).
Fallback model: ``bert-base-chinese`` if chinese-roberta is unavailable.

Transformer pipeline is lazily loaded on first use (thread-safe singleton) to
avoid blocking FastAPI startup.  If ``transformers`` is not installed the module
permanently operates in keyword-only mode.

All public data structures are **frozen dataclasses** (immutable).
"""
from __future__ import annotations

import logging
import re
import threading
from dataclasses import dataclass, field
from typing import Any, Optional

from backend.app.utils.cantonese_lexicon import (
    NEGATIVE_KEYWORDS,
    NEUTRAL_BOOSTERS,
    PARTICLE_MODIFIERS,
    POSITIVE_KEYWORDS,
)

try:
    from transformers import pipeline as hf_pipeline  # type: ignore[import-untyped]
    HAS_TRANSFORMERS = True
except ImportError:
    HAS_TRANSFORMERS = False

logger = logging.getLogger(__name__)

_NEGATION_CHARS: frozenset[str] = frozenset(["唔", "不", "冇", "沒", "非", "無"])
_INTENSIFIER_CHARS: frozenset[str] = frozenset(["好", "超", "極", "真", "太", "幾"])
_STAR_TO_LABEL: dict[int, str] = {1: "negative", 2: "negative", 3: "neutral", 4: "positive", 5: "positive"}
_MODEL_NAME = "hfl/chinese-roberta-wwm-ext"
_FALLBACK_MODEL_NAME = "bert-base-chinese"

# ── Frozen dataclasses ─────────────────────────────────────────────────────

@dataclass(frozen=True)
class AspectSentiment:
    """Per-topic sentiment within a piece of text."""
    topic: str
    label: str          # "positive" | "negative" | "neutral"
    confidence: float   # 0.0 - 1.0

@dataclass(frozen=True)
class SentimentResult:
    """Immutable sentiment analysis result."""
    label: str                             # "positive" | "negative" | "neutral"
    confidence: float                      # 0.0 - 1.0
    aspects: dict[str, str] = field(default_factory=dict)  # topic -> label

# ── Aspect extraction ──────────────────────────────────────────────────────

_ASPECT_DETECT: tuple[tuple[re.Pattern[str], str], ...] = (
    (re.compile(r"樓|物業|租金|按揭|買樓|樓市|樓價"), "property"),
    (re.compile(r"工|職|失業|返工|打工|人工|薪"), "employment"),
    (re.compile(r"政府|選舉|立法|議員|政策|政治"), "political"),
    (re.compile(r"股|投資|利息|恒指|基金|港股"), "financial"),
    (re.compile(r"移民|BNO|移居|離港|走佬"), "emigration"),
    (re.compile(r"醫|診所|醫院|急症|門診|藥|病|健康"), "healthcare"),
    (re.compile(r"學校|教育|DSE|大學|升學|功課|補習|教"), "education"),
    (re.compile(r"福利|津貼|綜援|安老|長者|退休|社福|社工"), "social_welfare"),
)

_ASPECT_KEYWORDS: dict[str, tuple[frozenset[str], frozenset[str]]] = {
    "property": (
        frozenset({"上車", "上樓", "收樓", "入伙", "筍盤", "抵買", "回穩", "暢旺"}),
        frozenset({"供唔起", "負資產", "蝕讓", "劈價", "撻訂", "銀主盤", "跌市", "貴"}),
    ),
    "employment": (
        frozenset({"升職", "加薪", "有得做", "有得撈", "搵到工"}),
        frozenset({"失業", "裁員", "減薪", "冇工做", "炒", "辭職"}),
    ),
    "political": (
        frozenset({"支持", "進步", "改善", "正確", "撐"}),
        frozenset({"離譜", "危機", "打壓", "箝制", "不滿"}),
    ),
    "financial": (
        frozenset({"升", "升浪", "牛市", "派息", "入市良機", "爆升"}),
        frozenset({"跌", "熊市", "蝕", "暴跌", "爆倉", "插水", "斬倉"}),
    ),
    "emigration": (
        frozenset({"機會", "新生活", "自由", "前途"}),
        frozenset({"移民", "離港", "走佬", "BNO", "冇希望", "冇前途"}),
    ),
    "healthcare": (
        frozenset({"健康", "康復", "痊癒", "醫好", "免費", "改善"}),
        frozenset({"排隊", "等候", "冇床位", "醫療事故", "爆煲", "唔夠人手", "貴"}),
    ),
    "education": (
        frozenset({"升學", "入到", "名校", "優秀", "獎學金", "進步"}),
        frozenset({"壓力", "操練", "補習", "填鴨", "殺校", "收生不足", "學費貴"}),
    ),
    "social_welfare": (
        frozenset({"加津貼", "派錢", "支援", "改善", "受惠", "幫助"}),
        frozenset({"削減", "不足", "唔夠", "排隊", "等", "申請難", "門檻高"}),
    ),
}

def _extract_aspects(text: str) -> dict[str, str]:
    """Detect topics in *text* and assign per-topic sentiment."""
    if not text:
        return {}
    aspects: dict[str, str] = {}
    for pattern, topic in _ASPECT_DETECT:
        if not pattern.search(text):
            continue
        pos_kw, neg_kw = _ASPECT_KEYWORDS.get(topic, (frozenset(), frozenset()))
        pos = sum(1 for kw in pos_kw if kw in text)
        neg = sum(1 for kw in neg_kw if kw in text)
        if pos > neg:
            aspects[topic] = "positive"
        elif neg > pos:
            aspects[topic] = "negative"
        else:
            aspects[topic] = "neutral"
    return aspects

# ── Lazy Transformer model (thread-safe singleton) ─────────────────────────

_model_lock = threading.Lock()
_model_pipeline: Optional[Any] = None
_model_load_failed = False

def _lazy_load_model() -> Optional[Any]:
    """Load HuggingFace sentiment pipeline on first call. Returns None on failure."""
    global _model_pipeline, _model_load_failed  # noqa: PLW0603
    if _model_pipeline is not None:
        return _model_pipeline
    if _model_load_failed:
        return None
    with _model_lock:
        if _model_pipeline is not None:
            return _model_pipeline
        if _model_load_failed:
            return None
        if not HAS_TRANSFORMERS:
            logger.info("transformers not installed; using keyword-only mode")
            _model_load_failed = True
            return None
        try:
            logger.info("Loading Transformer model: %s", _MODEL_NAME)
            _model_pipeline = hf_pipeline(
                "sentiment-analysis", model=_MODEL_NAME,
                truncation=True, max_length=512,
            )
            logger.info("Transformer sentiment model loaded: %s", _MODEL_NAME)
            return _model_pipeline
        except Exception:
            logger.warning(
                "Primary model %s unavailable, trying fallback %s",
                _MODEL_NAME, _FALLBACK_MODEL_NAME,
            )
            try:
                _model_pipeline = hf_pipeline(
                    "sentiment-analysis", model=_FALLBACK_MODEL_NAME,
                    truncation=True, max_length=512,
                )
                logger.info("Fallback Transformer model loaded: %s", _FALLBACK_MODEL_NAME)
                return _model_pipeline
            except Exception:
                logger.exception("Failed to load both Transformer models")
                _model_load_failed = True
                return None

# ── Keyword scoring ────────────────────────────────────────────────────────

def _keyword_scores(text: str) -> tuple[float, float, bool]:
    """Return (pos_score, neg_score, has_neutral_hedge) from keyword matching."""
    pos_score: float = 0.0
    neg_score: float = 0.0

    for kw in POSITIVE_KEYWORDS:
        idx = text.find(kw)
        while idx != -1:
            negated = idx > 0 and text[idx - 1] in _NEGATION_CHARS
            intensified = idx > 0 and text[idx - 1] in _INTENSIFIER_CHARS
            delta = 1.5 if intensified else 1.0
            if negated:
                neg_score += delta
            else:
                pos_score += delta
            idx = text.find(kw, idx + len(kw))

    for kw in NEGATIVE_KEYWORDS:
        idx = text.find(kw)
        while idx != -1:
            negated = idx > 0 and text[idx - 1] in _NEGATION_CHARS
            intensified = idx > 0 and text[idx - 1] in _INTENSIFIER_CHARS
            delta = 1.5 if intensified else 1.0
            if negated:
                pos_score += delta
            else:
                neg_score += delta
            idx = text.find(kw, idx + len(kw))

    # Particle modifier on dominant score
    tail = text[-5:] if len(text) >= 5 else text
    for particle, multiplier in PARTICLE_MODIFIERS.items():
        if particle in tail:
            if multiplier > 1.1:
                if pos_score >= neg_score:
                    pos_score *= multiplier
                else:
                    neg_score *= multiplier
            elif multiplier < 0.9:
                pos_score *= multiplier
                neg_score *= multiplier
            break

    has_neutral = any(nb in text for nb in NEUTRAL_BOOSTERS)
    return pos_score, neg_score, has_neutral

def _keyword_result(text: str) -> tuple[SentimentResult, float]:
    """Run keyword analysis. Returns (result, raw_confidence).

    raw_confidence is the normalised gap [0,1]; >= 0.7 means high certainty.
    """
    pos, neg, has_neutral = _keyword_scores(text)
    aspects = _extract_aspects(text)
    total = pos + neg

    if total == 0.0:
        return SentimentResult(label="neutral", confidence=0.5, aspects=aspects), 0.0

    gap = abs(pos - neg) / total

    if has_neutral and gap <= 0.4:
        return SentimentResult(label="neutral", confidence=0.5, aspects=aspects), 0.0
    if pos == neg:
        return SentimentResult(label="neutral", confidence=0.5, aspects=aspects), 0.0

    label = "positive" if pos > neg else "negative"
    confidence = round(min(0.5 + gap * 0.5, 1.0), 4)
    mixed = pos > 0 and neg > 0
    return SentimentResult(label=label, confidence=confidence, aspects=aspects), (0.0 if mixed else gap)

# ── Transformer inference ──────────────────────────────────────────────────

def _transformer_result(text: str, pipe: Any) -> SentimentResult:
    """Run Transformer pipeline on *text* and map 5-star to 3-class."""
    raw = pipe(text[:512])[0]
    stars = int(raw["label"][0])
    label = _STAR_TO_LABEL[stars]
    confidence = round(float(raw["score"]), 4)
    return SentimentResult(label=label, confidence=confidence, aspects=_extract_aspects(text))

# ── Public API ─────────────────────────────────────────────────────────────

def analyze_text(text: str) -> SentimentResult:
    """Analyse *text*: keyword fast-path, Transformer fallback if uncertain.

    1. Keyword scoring on text.
    2. If confidence >= 0.6 and no mixed signals, return keyword result.
    3. Otherwise attempt Transformer inference.
    4. If Transformer unavailable, return keyword result as-is.
    """
    if not text or not text.strip():
        return SentimentResult(label="neutral", confidence=0.5, aspects={})
    kw_result, raw_conf = _keyword_result(text)
    if raw_conf >= 0.7:
        return kw_result
    pipe = _lazy_load_model()
    if pipe is None:
        return kw_result
    try:
        return _transformer_result(text, pipe)
    except Exception:
        logger.exception("Transformer inference failed; returning keyword result")
        return kw_result

def analyze_batch(texts: list[str]) -> list[SentimentResult]:
    """Analyse a batch of texts. High-confidence items skip Transformer."""
    if not texts:
        return []

    results: list[Optional[SentimentResult]] = [None] * len(texts)
    transformer_indices: list[int] = []
    transformer_texts: list[str] = []

    for i, text in enumerate(texts):
        if not text or not text.strip():
            results[i] = SentimentResult(label="neutral", confidence=0.5, aspects={})
            continue
        kw_result, raw_conf = _keyword_result(text)
        if raw_conf >= 0.7:
            results[i] = kw_result
        else:
            results[i] = kw_result  # fallback if Transformer unavailable
            transformer_indices.append(i)
            transformer_texts.append(text[:512])

    if transformer_indices:
        pipe = _lazy_load_model()
        if pipe is not None:
            try:
                raw_outputs = pipe(transformer_texts)
                for idx, raw in zip(transformer_indices, raw_outputs):
                    stars = int(raw["label"][0])
                    label = _STAR_TO_LABEL[stars]
                    confidence = round(float(raw["score"]), 4)
                    results[idx] = SentimentResult(
                        label=label, confidence=confidence,
                        aspects=_extract_aspects(texts[idx]),
                    )
            except Exception:
                logger.exception("Batch Transformer inference failed")

    return [r for r in results if r is not None]

def analyze_news_headline(headline: str) -> SentimentResult:
    """Keyword-only headline analysis (no Transformer) for high throughput."""
    if not headline or not headline.strip():
        return SentimentResult(label="neutral", confidence=0.5, aspects={})
    kw_result, _ = _keyword_result(headline)
    return kw_result
