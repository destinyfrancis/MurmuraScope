"""Unit tests for lite_hooks i18n / locale support (Phase 3.2).

Covers:
- deliberate_lite(locale="zh") returns Chinese emotional reaction and reasoning
- deliberate_lite(locale="en") returns English emotional reaction and reasoning
- _EMOTIONAL_REACTIONS_EN has all four VAD quadrant keys
- Default locale is "zh" (backward compatible)
- Reasoning templates differ by locale
- No crash on observe decision with either locale
"""

from __future__ import annotations

import random

import pytest

from backend.app.services.lite_hooks import (
    _EMOTIONAL_REACTIONS,
    _EMOTIONAL_REACTIONS_EN,
    deliberate_lite,
    generate_lite_events,
)


_QUADRANTS = ("high_arousal_neg", "high_arousal_pos", "low_arousal_neg", "low_arousal_pos")


class TestEmotionalReactionDicts:
    def test_zh_dict_has_all_quadrants(self):
        for q in _QUADRANTS:
            assert q in _EMOTIONAL_REACTIONS, f"Missing quadrant: {q}"

    def test_en_dict_has_all_quadrants(self):
        for q in _QUADRANTS:
            assert q in _EMOTIONAL_REACTIONS_EN, f"Missing EN quadrant: {q}"

    def test_en_values_are_ascii(self):
        for q, labels in _EMOTIONAL_REACTIONS_EN.items():
            for label in labels:
                assert label.isascii(), f"Non-ASCII label '{label}' in EN dict quadrant {q}"

    def test_zh_values_are_non_empty(self):
        for q, labels in _EMOTIONAL_REACTIONS.items():
            assert len(labels) >= 2, f"Too few labels in ZH quadrant {q}"

    def test_en_values_are_non_empty(self):
        for q, labels in _EMOTIONAL_REACTIONS_EN.items():
            assert len(labels) >= 2, f"Too few labels in EN quadrant {q}"


class TestDeliberateLiteLocaleZH:
    """Default (zh) locale — backward compatibility tests."""

    def test_default_locale_is_zh(self):
        """Calling without locale= should behave as locale='zh'."""
        result_default = deliberate_lite(
            agent={"id": "a1"},
            beliefs={},
            events=[],
        )
        result_zh = deliberate_lite(
            agent={"id": "a1"},
            beliefs={},
            events=[],
            locale="zh",
        )
        assert result_default.decision == result_zh.decision

    def test_zh_observe_reaction_is_chinese(self):
        result = deliberate_lite(
            agent={"id": "a1"},
            beliefs={},
            events=[],
            locale="zh",
        )
        # observe → 觀望 (Chinese fallback)
        assert result.emotional_reaction == "觀望"

    def test_zh_reasoning_contains_chinese(self):
        events = generate_lite_events(
            round_number=1,
            active_metrics=("economy",),
            prev_dominant_stance={"economy": 0.5},
            event_history=[],
            rng=random.Random(42),
        )
        result = deliberate_lite(
            agent={"id": "a1", "openness": 0.8},
            beliefs={"economy": 0.5},
            events=events,
            locale="zh",
            rng=random.Random(42),
        )
        # ZH reasoning must contain Chinese characters
        has_chinese = any("\u4e00" <= ch <= "\u9fff" for ch in result.reasoning)
        assert has_chinese, f"No Chinese chars in reasoning: {result.reasoning!r}"


class TestDeliberateLiteLocaleEN:
    def test_en_observe_reaction_is_english(self):
        result = deliberate_lite(
            agent={"id": "a1"},
            beliefs={},
            events=[],
            locale="en",
        )
        assert result.emotional_reaction == "observing"

    def test_en_reasoning_is_ascii(self):
        events = generate_lite_events(
            round_number=1,
            active_metrics=("economy",),
            prev_dominant_stance={"economy": 0.5},
            event_history=[],
            rng=random.Random(42),
        )
        result = deliberate_lite(
            agent={"id": "a1", "openness": 0.8},
            beliefs={"economy": 0.5},
            events=events,
            locale="en",
            rng=random.Random(42),
        )
        assert result.reasoning.isascii(), f"EN reasoning contains non-ASCII: {result.reasoning!r}"

    def test_en_reasoning_contains_decision_word(self):
        events = generate_lite_events(
            round_number=1,
            active_metrics=("x",),
            prev_dominant_stance={"x": 0.5},
            event_history=[],
            rng=random.Random(42),
        )
        result = deliberate_lite(
            agent={"id": "a1", "openness": 0.9},
            beliefs={"x": 0.5},
            events=events,
            locale="en",
            rng=random.Random(42),
        )
        assert result.decision in result.reasoning, \
            f"Decision '{result.decision}' not in reasoning: {result.reasoning!r}"

    def test_en_no_events_stable_message(self):
        result = deliberate_lite(
            agent={"id": "a1"},
            beliefs={},
            events=[],
            locale="en",
        )
        assert "stable" in result.reasoning.lower() or "monitor" in result.reasoning.lower()

    def test_en_emotional_reaction_from_dict(self):
        """With emotional_state provided, reaction should come from EN dict."""

        class FakeEmotionState:
            valence = -0.8
            arousal = 0.9  # high arousal, negative valence → high_arousal_neg

        result = deliberate_lite(
            agent={"id": "a1"},
            beliefs={},
            events=[],
            emotional_state=FakeEmotionState(),
            locale="en",
            rng=random.Random(42),
        )
        assert result.emotional_reaction in _EMOTIONAL_REACTIONS_EN["high_arousal_neg"]

    def test_zh_emotional_reaction_from_dict(self):
        """With emotional_state provided and locale=zh, reaction from ZH dict."""

        class FakeEmotionState:
            valence = 0.8
            arousal = 0.9  # high_arousal_pos

        result = deliberate_lite(
            agent={"id": "a1"},
            beliefs={},
            events=[],
            emotional_state=FakeEmotionState(),
            locale="zh",
            rng=random.Random(42),
        )
        assert result.emotional_reaction in _EMOTIONAL_REACTIONS["high_arousal_pos"]


class TestLocaleNeutralBehaviour:
    """Decisions and belief_updates should be identical regardless of locale."""

    def test_decisions_same_across_locales(self):
        events = generate_lite_events(
            round_number=3,
            active_metrics=("gdp", "trust"),
            prev_dominant_stance={"gdp": 0.6, "trust": 0.4},
            event_history=[],
            rng=random.Random(7),
        )
        agent = {"id": "a1", "openness": 0.7, "neuroticism": 0.4}
        beliefs = {"gdp": 0.6, "trust": 0.4}

        zh = deliberate_lite(agent=agent, beliefs=beliefs, events=events, locale="zh", rng=random.Random(7))
        en = deliberate_lite(agent=agent, beliefs=beliefs, events=events, locale="en", rng=random.Random(7))

        assert zh.decision == en.decision
        assert zh.belief_updates == en.belief_updates
        assert zh.topic_tags == en.topic_tags
