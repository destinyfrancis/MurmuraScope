"""US English locale constants for domain packs."""

from __future__ import annotations

from backend.app.domain.base import DemographicsSpec, PromptLocale, SentimentLexicon

EN_US_LOCALE = PromptLocale(
    language_code="en-US",
    language_rule="[LANGUAGE RULE] All posts must be in English. Use casual American English.",
    personality_descriptions={
        "openness": {
            "high": "Intellectually curious, open to new ideas, creative and imaginative",
            "low": "Practical, conventional, prefers routine and familiar experiences",
        },
        "conscientiousness": {
            "high": "Organized, disciplined, goal-oriented, detail-focused",
            "low": "Flexible, spontaneous, sometimes disorganized",
        },
        "extraversion": {
            "high": "Outgoing, energetic, talkative, enjoys social gatherings",
            "low": "Reserved, quiet, prefers solitude or small groups",
        },
        "agreeableness": {
            "high": "Cooperative, trusting, helpful, empathetic",
            "low": "Competitive, skeptical, independent-minded",
        },
        "neuroticism": {
            "high": "Emotionally reactive, prone to stress and worry",
            "low": "Emotionally stable, calm under pressure, resilient",
        },
    },
    housing_context={
        "Own": "You own your home and have monthly mortgage payments.",
        "Rent": "You rent your apartment and face annual rent increases.",
        "Subsidized": "You live in subsidized housing with below-market rent.",
    },
    concern_templates={
        "low_income": (
            "You worry about making ends meet, healthcare costs, and affording groceries."
        ),
        "mid_income": (
            "You're concerned about saving for retirement, your children's education, "
            "and housing costs."
        ),
        "high_income": (
            "You focus on investment returns, tax optimization, and wealth preservation."
        ),
    },
    posting_guidelines=(
        "You post on social media like Reddit/Twitter. You share opinions about markets, "
        "economy, and daily life. Use hashtags occasionally. React to news and other "
        "people's posts."
    ),
)

EN_US_SENTIMENT = SentimentLexicon(
    positive_keywords=frozenset({
        "bullish", "rally", "growth", "confident", "recovery", "upside",
        "optimistic", "boom", "surge", "gain", "profit", "strong",
        "breakthrough", "innovation", "opportunity", "upgrade",
        "positive", "improving", "thriving", "expanding", "hiring",
        "beat", "outperform", "record", "milestone", "success",
    }),
    negative_keywords=frozenset({
        "bearish", "crash", "recession", "layoffs", "inflation", "downside",
        "pessimistic", "bust", "plunge", "loss", "deficit", "weak",
        "crisis", "collapse", "default", "downgrade", "selloff",
        "negative", "declining", "struggling", "contracting", "firing",
        "miss", "underperform", "warning", "risk", "failure",
    }),
    intensifiers=frozenset({
        "very", "extremely", "absolutely", "significantly", "dramatically",
        "massively", "incredibly", "hugely", "totally", "completely",
    }),
)
