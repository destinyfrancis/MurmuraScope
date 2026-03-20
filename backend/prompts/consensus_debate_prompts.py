# backend/prompts/consensus_debate_prompts.py
"""LLM prompt templates for ConsensusDebateEngine.

Firewall-protected multi-agent debate mechanism:
  Phase 1: Agent receives opposing beliefs from paired agent
  Phase 2: Agent produces rebuttal/concession grounded in persona + memories
  Phase 3: Belief delta extracted for Bayesian update

All prompts enforce the Knowledge Firewall directive.
"""

from __future__ import annotations

DEBATE_SYSTEM = """\
You are simulating Agent "{agent_name}" in a structured debate within a \
multi-agent social simulation.

AGENT PROFILE:
- Role: {agent_role}
- Persona: {agent_persona}
- Current stance on "{topic}": {agent_stance:.2f} (0.0 = strongly oppose, \
1.0 = strongly support)

KNOWLEDGE FIREWALL -- CRITICAL:
You must reason ONLY from the agent's profile, memories, and the scenario \
context provided below. Do NOT use your training knowledge about events, \
outcomes, or plot developments that occur AFTER the time horizon described \
in the scenario. Predictions and arguments must emerge from the provided \
data, not from foreknowledge of real or fictional outcomes.

YOUR TASK:
Another agent has presented an opposing view on the topic "{topic}". \
You must respond IN CHARACTER as {agent_name}:
1. Consider their argument carefully
2. Decide whether to REBUT (defend your position) or CONCEDE (shift toward \
   their view) based on YOUR persona, goals, and available evidence
3. Provide a brief reasoning grounded in your character

IMPORTANT: Agents with high openness are more willing to concede. \
Agents with high neuroticism react more strongly to threatening arguments. \
Agents with high conscientiousness weigh evidence more carefully.

Return ONLY valid JSON:
{{
  "response_type": "rebut" or "concede" or "partial_concede",
  "argument": "<1-2 sentences: your in-character response to the opposing view>",
  "belief_delta": <float -0.15 to 0.15: how much your stance shifts on this \
topic. Negative = moved away from opponent, 0 = unchanged, positive = moved \
toward opponent>,
  "emotional_impact": "<one word: confident|defensive|anxious|curious|angry|\
resigned|inspired>",
  "confidence": <float 0.0-1.0: how confident you are in your position after \
hearing the opposing view>
}}"""

DEBATE_USER = """\
## Scenario Context
{scenario_description}

## Your Recent Memories
{agent_memories}

## Your Current Beliefs
{agent_beliefs_json}

---

## Opposing Agent: {opponent_name} ({opponent_role})
Their stance on "{topic}": {opponent_stance:.2f}
Their argument:
"{opponent_argument}"

---

Respond as {agent_name}. Return ONLY valid JSON."""
