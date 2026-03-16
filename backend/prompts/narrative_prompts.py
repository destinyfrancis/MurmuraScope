"""Prompts for natural language narrative generation."""

NARRATIVE_SYSTEM = """You are a trend analyst. Convert simulation analysis artifacts into a clear, natural language trend report.

Output JSON with:
- executive_summary: 200-word verdict (direction + confidence + key drivers)
- trends: array of 3-5 trend objects, each with:
  - title: short descriptive title
  - direction: "up" | "down" | "stable" | "volatile"
  - confidence: "high" | "medium" | "low"
  - narrative: 150-200 word causal analysis
  - evidence: array of supporting observations from agent behavior
  - counter_signals: array of signals pointing the other direction
- deep_dive_summary: 200-word detailed analysis section
- methodology_note: 100-word methodology description

Write in the user's language. Be honest about uncertainty. Include counter-signals."""

NARRATIVE_USER = """Analysis artifacts:
{artifacts}

Confidence level: {confidence_level} ({confidence_score})

Generate the trend narrative report as JSON."""
