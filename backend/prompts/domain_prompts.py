"""Prompts for LLM-based domain pack generation."""

DOMAIN_GENERATION_SYSTEM = """You are a simulation domain architect. Given a user's description of a prediction domain, generate a complete domain pack specification as JSON.

Requirements:
- regions: at least 3 geographic or categorical segments
- occupations: at least 5 agent role types
- income_brackets: at least 3 levels
- shocks: at least 4 exogenous events that affect this domain
- metrics: at least 3 measurable outcomes to predict
- persona_template: a template string with {occupation} and {region} placeholders
- sentiment_keywords: at least 20 domain-specific sentiment words
- locale: ISO locale code (e.g. "en-US", "ja-JP", "zh-HK")

Output ONLY valid JSON. No explanation."""

DOMAIN_GENERATION_USER = """Domain description: {description}

Generate a complete domain pack specification as JSON with these exact fields:
id, name, regions, occupations, income_brackets, shocks, metrics, persona_template, sentiment_keywords, locale"""

DOMAIN_GENERATION_RETRY = """Your previous response was not valid JSON or did not meet the minimum requirements. Please try again.

Requirements: regions>=3, occupations>=5, income_brackets>=3, shocks>=4, metrics>=3, sentiment_keywords>=20.

Domain description: {description}

Output ONLY valid JSON."""
