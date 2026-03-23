# Wiring Upgrade Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Connect all disconnected simulation infrastructure and replace Tier 1/2 with stochastic activation, so every activated agent uses LLM and all built features actually affect simulation behavior.

**Architecture:** Phase 0 removes the Tier system and introduces stochastic per-round agent activation with model routing. Phases 1-3 wire 8 disconnected features into the simulation pipeline in Group execution order. Test fixes happen last in a single batch.

**Tech Stack:** Python 3.11, FastAPI, aiosqlite, Pydantic V2 (frozen models), LanceDB (384-dim embeddings), OASIS subprocess framework

**Spec:** `docs/superpowers/specs/2026-03-21-wiring-upgrade-design.md` (rev 2)

---

## File Map

### New Files
| File | Responsibility |
|------|---------------|
| `backend/tests/test_stochastic_activation.py` | Activation determinism, distribution, stakeholder floor |
| `backend/tests/test_bayesian_update.py` | True Bayes formula on both scales, edge cases |
| `backend/tests/test_feed_cognition.py` | Feed items appear in LLM prompt context |
| `backend/tests/test_debate_db_persist.py` | Debate deltas persist to belief_states table |
| `backend/tests/test_branch_full_copy.py` | All dynamic state tables copied on branch |
| `backend/tests/test_shock_macro.py` | Shock with macro_effects changes MacroState |
| `backend/tests/test_relationship_dissolution.py` | Gottman > 0.8 triggers DISSOLVED |

### Modified Files
| File | What Changes |
|------|-------------|
| `backend/app/services/simulation_runner.py` | Remove tier loading (~L1387-1407); add `get_active_agents_for_round()`; remove all `tier1_agents` guards; add memory/feed retrieval before decisions; add debate DB persistence; wire relationship trust into decision context |
| `backend/app/models/kg_session_state.py` | Rename `tier1_agents` → `stakeholder_agents`; remove tier fields |
| `backend/database/schema.sql` | Add `activity_level`, `influence_weight`, `is_stakeholder` to agent_profiles |
| `backend/app/services/kg_agent_factory.py` | Generate activity_level + influence_weight + is_stakeholder during profile creation |
| `backend/app/services/agent_factory.py` | Infer activity_level + influence_weight + is_stakeholder from HK demographics |
| `backend/app/services/scenario_generator.py` | Extend LLM prompt to output `stakeholder_entity_types` |
| `backend/prompts/scenario_generation_prompts.py` | Add stakeholder_entity_types to output schema |
| `backend/app/utils/llm_client.py` | Add `get_agent_model(is_stakeholder)` + `AGENT_LLM_MODEL_LITE` env var |
| `backend/app/models/simulation_config.py` | Add `activation_seed` to session request |
| `backend/app/services/belief_system.py` | Add `bayesian_update()`, `_stance_to_prob()`, `_prob_to_stance()`, `compute_likelihood_ratio()` |
| `backend/app/services/belief_propagation.py` | Use `bayesian_update()` in cascade on [0,1] scale |
| `backend/app/services/feed_ranker.py` | Add `get_agent_feed()` DB query helper |
| `backend/prompts/decision_prompts.py` | Add `{recent_memories}`, `{feed_context}`, `{fingerprint}`, `{trusted_agents}` placeholders |
| `backend/app/services/cognitive_agent_engine.py` | Extend `_build_deliberation_prompt()` with feed + memory for all active agents |
| `backend/app/services/relationship_lifecycle.py` | Add Gottman > 0.8 dissolution trigger |
| `backend/app/services/emotional_engine.py` | Add relationship crisis → VAD impact |
| `backend/app/models/request.py` | Add `macro_effects: Optional[dict]` to ScheduledShock |
| `backend/app/api/simulation.py` | Wire shock macro_effects to MacroController |
| `backend/app/services/macro_shocks.py` | Add generic `apply_macro_effects()` handler |
| `backend/app/api/simulation_branches.py` | Expand copy to all dynamic state tables |
| `backend/app/services/swarm_ensemble.py` | Fix kg_nodes column names; add agent_relationships + kg_edges + cognitive_dissonance copy |
| `backend/app/services/auto_fork_service.py` | Expand copy to match swarm_ensemble |
| `backend/app/services/agent_factory.py` | Add `_infer_fingerprint_from_demographics()` |

---

## Task 1: Schema + KGSessionState + Config Changes

**Files:**
- Modify: `backend/database/schema.sql` (agent_profiles CREATE TABLE)
- Modify: `backend/app/models/kg_session_state.py` (full file, ~77 lines)
- Modify: `backend/app/models/simulation_config.py` (~L8-95)
- Modify: `backend/app/models/request.py` (~L41-48, ScheduledShock)

- [ ] **Step 1: Add columns to schema.sql**

In `backend/database/schema.sql`, find the `CREATE TABLE agent_profiles` statement and add after the last column before the closing paren:

```sql
    activity_level REAL DEFAULT 0.5,
    influence_weight REAL DEFAULT 1.0,
    is_stakeholder INTEGER DEFAULT 0,
```

- [ ] **Step 2: Rename tier1_agents in kg_session_state.py**

In `backend/app/models/kg_session_state.py`, replace all occurrences of `tier1_agents` with `stakeholder_agents`. The field definition changes from:
```python
tier1_agents: list[dict[str, Any]] = field(default_factory=list)
```
to:
```python
stakeholder_agents: list[dict[str, Any]] = field(default_factory=list)
```

- [ ] **Step 3: Add activation_seed to simulation config**

In `backend/app/models/simulation_config.py`, find the `HookConfig` dataclass and add:
```python
    activation_seed: int | None = None
```

- [ ] **Step 4: Add macro_effects to ScheduledShock**

In `backend/app/models/request.py`, find `class ScheduledShock` (~line 41) and add:
```python
    macro_effects: dict[str, float] | None = None
```

- [ ] **Step 5: Grep for all tier1_agents references across codebase**

Run: `grep -rn "tier1_agents" backend/ --include="*.py"`

Rename every occurrence to `stakeholder_agents`. Expected files: `simulation_runner.py`, `kg_session_state.py`, any tests referencing tier1.

- [ ] **Step 6: Commit**

```bash
git add backend/database/schema.sql backend/app/models/kg_session_state.py backend/app/models/simulation_config.py backend/app/models/request.py backend/app/services/simulation_runner.py
git commit -m "refactor: rename tier1_agents to stakeholder_agents; add activation schema fields"
```

---

## Task 2: LLM Model Routing

**Files:**
- Modify: `backend/app/utils/llm_client.py` (~L159-172)

- [ ] **Step 1: Add AGENT_LLM_MODEL_LITE env var + routing function**

In `backend/app/utils/llm_client.py`, after the existing `get_agent_provider_model()` function (~line 172), add:

```python
def get_agent_model(is_stakeholder: bool = True) -> tuple[str, str]:
    """Return (provider, model) with model routing based on stakeholder status.

    Stakeholders use AGENT_LLM_MODEL (stronger model).
    Background agents use AGENT_LLM_MODEL_LITE (cheaper model).
    Falls back to AGENT_LLM_MODEL if LITE not set.
    """
    if is_stakeholder:
        return get_agent_provider_model()
    provider = os.environ.get("AGENT_LLM_PROVIDER") or get_default_provider()
    lite_model = os.environ.get("AGENT_LLM_MODEL_LITE")
    if lite_model:
        return provider, lite_model
    return get_agent_provider_model()
```

- [ ] **Step 2: Commit**

```bash
git add backend/app/utils/llm_client.py
git commit -m "feat: add LLM model routing for stakeholder vs background agents"
```

---

## Task 3: Stochastic Activation in SimulationRunner

**Files:**
- Modify: `backend/app/services/simulation_runner.py` (~L1387-1407, plus all tier1_agents guards)

- [ ] **Step 1: Replace tier loading with stakeholder loading + activation function**

In `simulation_runner.py`, find the tier loading block inside `_load_kg_driven_state()` (~lines 1387-1407). Replace the `LIMIT 30` query with a query that loads ALL agents and marks stakeholders:

```python
# Load stakeholder agents (no hard limit — determined by scenario)
cursor = await db.execute(
    """SELECT id, oasis_username AS name,
              json_extract(properties, '$.role') AS role,
              json_extract(properties, '$.faction') AS faction,
              is_stakeholder,
              activity_level
       FROM agent_profiles
       WHERE session_id = ?
       ORDER BY CAST(json_extract(properties, '$.importance') AS REAL) DESC""",
    (session_id,),
)
rows = await cursor.fetchall()
stakeholders = []
for r in rows:
    agent_dict = {
        "id": r["id"],
        "name": r["name"] or "",
        "role": r["role"] or "",
        "faction": r["faction"] or "none",
        "is_stakeholder": bool(r["is_stakeholder"]),
        "activity_level": r["activity_level"] or 0.5,
    }
    if agent_dict["is_stakeholder"]:
        stakeholders.append(agent_dict)
self._kg_sessions[session_id].stakeholder_agents = stakeholders
```

- [ ] **Step 2: Add get_active_agents_for_round() method**

Add this method to the SimulationRunner class:

```python
def get_active_agents_for_round(
    self,
    session_id: str,
    round_num: int,
    all_agents: list[dict],
    seed: int | None = None,
) -> list[dict]:
    """Stochastic activation: each agent independently activated by activity_level probability."""
    rng = random.Random(f"{seed}_{round_num}" if seed else None)
    active = []
    for agent in all_agents:
        level = agent.get("activity_level", 0.5)
        # Stakeholder floor
        if agent.get("is_stakeholder"):
            level = max(level, 0.8)
        if rng.random() < level:
            active.append(agent)
    return active
```

- [ ] **Step 3: Remove all tier1_agents guard checks in kg_driven hooks**

Search for all places in simulation_runner.py that check `kg_state.stakeholder_agents` (formerly `tier1_agents`) to gate hook execution. Replace the pattern:

```python
# OLD: only Tier 1 agents
for agent in kg_state.stakeholder_agents:
    ...
```

with:

```python
# NEW: all active agents this round
active_agents = self.get_active_agents_for_round(
    session_id, round_num, all_agent_dicts,
    seed=kg_state.activation_seed,
)
for agent in active_agents:
    ...
```

Key locations to update:
- `_kg_tier1_deliberation()` (~L1634-1708) — rename to `_kg_deliberation()`
- `_kg_strategic_planning()` (~L1817-1838)
- `_kg_consensus_debate()` (~L1842-1863)

- [ ] **Step 4: Commit**

```bash
git add backend/app/services/simulation_runner.py
git commit -m "feat: replace Tier system with stochastic activation model"
```

---

## Task 4: Stakeholder Identification in Agent Factories

**Files:**
- Modify: `backend/app/services/kg_agent_factory.py`
- Modify: `backend/app/services/agent_factory.py`
- Modify: `backend/app/services/scenario_generator.py`
- Modify: `backend/prompts/scenario_generation_prompts.py`

- [ ] **Step 1: Extend ScenarioGenerator prompt to output stakeholder_entity_types**

In `backend/prompts/scenario_generation_prompts.py`, find the output JSON schema section. Add to the schema:

```json
"stakeholder_entity_types": ["<entity types whose decisions materially affect scenario outcomes>"]
```

- [ ] **Step 2: Parse stakeholder_entity_types in scenario_generator.py**

In `backend/app/services/scenario_generator.py`, in `_parse_response()`, extract the new field:

```python
stakeholder_types = raw.get("stakeholder_entity_types", [])
```

Store on the returned `UniversalScenarioConfig` (add field if needed).

- [ ] **Step 3: Mark is_stakeholder in kg_agent_factory.py**

In `backend/app/services/kg_agent_factory.py`, after profile generation in `generate_from_kg()`, add stakeholder marking:

```python
# Mark stakeholders based on ScenarioGenerator output
for profile in profiles:
    profile_entity_type = getattr(profile, 'entity_type', '')
    profile.is_stakeholder = profile_entity_type in stakeholder_entity_types
    if profile.is_stakeholder:
        profile.activity_level = max(profile.activity_level, 0.8)
```

- [ ] **Step 4: Add activity_level + influence_weight generation to KGAgentFactory LLM prompt**

Extend the profile generation LLM prompt to include:
```
For each agent, also generate:
- activity_level (0.0-1.0): how frequently this actor participates in public discourse
- influence_weight (0.0-3.0): how visible this actor's communications are to others
```

- [ ] **Step 5: Infer HK mode behavioral params in agent_factory.py**

In `backend/app/services/agent_factory.py`, add to the profile generation logic:

```python
def _infer_behavioral_params(age: int, income: float, occupation: str) -> dict:
    """Infer activity_level and influence_weight from HK demographics."""
    if age <= 35:
        activity = 0.7 + random.random() * 0.2
    elif age <= 55:
        activity = 0.4 + random.random() * 0.2
    else:
        activity = 0.2 + random.random() * 0.2

    influence = 1.0
    if income > 50000:
        influence *= 1.3

    stakeholder_occupations = {"政府官員", "議員", "地產商", "銀行家", "記者", "教授"}
    is_stakeholder = occupation in stakeholder_occupations

    if is_stakeholder:
        activity = max(activity, 0.8)

    return {
        "activity_level": round(activity, 2),
        "influence_weight": round(influence, 2),
        "is_stakeholder": is_stakeholder,
    }
```

- [ ] **Step 6: Commit**

```bash
git add backend/app/services/kg_agent_factory.py backend/app/services/agent_factory.py backend/app/services/scenario_generator.py backend/prompts/scenario_generation_prompts.py
git commit -m "feat: add stakeholder identification + behavioral params to agent factories"
```

---

## Task 5: Episodic Memory → All Agent Decisions

**Files:**
- Modify: `backend/app/services/simulation_runner.py` (Group 2 decision step)
- Modify: `backend/prompts/decision_prompts.py` (~L17-31)
- Modify: `backend/app/services/cognitive_agent_engine.py` (~L140-215)

- [ ] **Step 1: Add {recent_memories} to HK mode decision prompt**

In `backend/prompts/decision_prompts.py`, add to the SYSTEM_PROMPT or the user prompt template:

```python
MEMORY_CONTEXT_BLOCK = """
最近記憶：
{recent_memories}
"""
```

Inject this block into the prompt when memories are available.

- [ ] **Step 2: Retrieve memories for all active agents in Group 2**

In `simulation_runner.py`, before the decision step in Group 2, add memory retrieval for each active agent:

```python
# Retrieve episodic memories for decision context
memory_context = await self._agent_memory.get_agent_context(
    session_id=session_id,
    agent_id=agent["id"],
    current_round=round_num,
    context_query=scenario_description,
)
```

Pass `memory_context` into both HK mode (`decision_prompts`) and kg_driven mode (`cognitive_agent_engine`) prompt builders.

- [ ] **Step 3: Extend cognitive_agent_engine deliberation for all active agents**

In `backend/app/services/cognitive_agent_engine.py`, the `_build_deliberation_prompt()` (~L140-215) already supports a memory block. Ensure the memory block is populated for ALL active agents, not just the former Tier 1.

- [ ] **Step 4: Commit**

```bash
git add backend/app/services/simulation_runner.py backend/prompts/decision_prompts.py backend/app/services/cognitive_agent_engine.py
git commit -m "feat: wire episodic memory retrieval into all agent decisions"
```

---

## Task 6: Cognitive Fingerprint → All Modes

**Files:**
- Modify: `backend/app/services/agent_factory.py`
- Modify: `backend/prompts/decision_prompts.py`

- [ ] **Step 1: Add fingerprint inference for HK mode**

In `backend/app/services/agent_factory.py`, add:

```python
def _infer_fingerprint_from_demographics(
    political_stance: float, age: int, income: float, education: str,
) -> dict[str, float]:
    """Infer cognitive fingerprint from HK demographic profile."""
    return {
        "authority": round(0.3 + 0.4 * (1.0 - political_stance), 2),
        "loyalty": round(0.4 + 0.3 * (1.0 - political_stance), 2),
        "openness": round(min(1.0, 0.3 + 0.02 * min(age, 40)), 2),
        "conformity": round(max(0.1, 0.6 - 0.01 * min(age, 40)), 2),
        "security": round(min(1.0, 0.3 + income / 100000), 2),
        "prestige": round(min(1.0, income / 80000), 2),
        "confirmation_bias": 0.5,
        "susceptibility": round(max(0.2, 0.7 - 0.01 * age), 2),
    }
```

Call this during HK agent profile creation and store in `properties` JSON.

- [ ] **Step 2: Inject fingerprint into HK decision prompt**

In `backend/prompts/decision_prompts.py`, add fingerprint context:

```python
FINGERPRINT_BLOCK = """
認知特徵：authority={authority}, loyalty={loyalty}, openness={openness}, conformity={conformity}
"""
```

- [ ] **Step 3: Commit**

```bash
git add backend/app/services/agent_factory.py backend/prompts/decision_prompts.py
git commit -m "feat: infer cognitive fingerprint for HK mode agents"
```

---

## Task 7: Feed Ranking → Agent Cognition Loop

**Files:**
- Modify: `backend/app/services/feed_ranker.py` (~L38-325)
- Modify: `backend/app/services/simulation_runner.py`
- Modify: `backend/prompts/decision_prompts.py`
- Modify: `backend/app/services/cognitive_agent_engine.py`

- [ ] **Step 1: Add get_agent_feed() to feed_ranker.py**

In `backend/app/services/feed_ranker.py`, add a new method:

```python
async def get_agent_feed(
    self, session_id: str, agent_id: int, round_number: int,
    limit: int = 5, db: Any = None,
) -> list[dict[str, Any]]:
    """Retrieve pre-ranked feed items for an agent from agent_feeds table."""
    if db is None:
        from backend.app.utils.db import get_db
        db = await get_db()
    cursor = await db.execute(
        """SELECT af.post_id, af.rank, af.score,
                  sa.content, sa.sentiment, sa.oasis_username
           FROM agent_feeds af
           JOIN simulation_actions sa ON sa.id = af.post_id AND sa.session_id = af.session_id
           WHERE af.session_id = ? AND af.agent_id = ? AND af.round_number = ?
           ORDER BY af.rank ASC
           LIMIT ?""",
        (session_id, agent_id, round_number, limit),
    )
    return [dict(r) for r in await cursor.fetchall()]
```

- [ ] **Step 2: Add diversity injection**

In the same file, add to `rank_feed()` or as a post-processing step:

```python
def _inject_diversity(
    self, ranked: list[dict], agent_stance: float, min_opposing: int = 1,
) -> list[dict]:
    """Ensure at least min_opposing items from opposing stance in top results."""
    opposing = [p for p in ranked if abs(p.get("stance", 0.5) - agent_stance) > 0.4]
    same = [p for p in ranked if p not in opposing]
    # Guarantee at least 1 opposing voice in top 5
    result = same[:4] + opposing[:min_opposing] if opposing else ranked[:5]
    return sorted(result, key=lambda x: x.get("score", 0), reverse=True)
```

- [ ] **Step 3: Wire feed into Group 2 decision context**

In `simulation_runner.py`, before the decision step:

```python
feed_items = await self._feed_ranker.get_agent_feed(
    session_id, agent["id"], round_num - 1, limit=5, db=db
)
feed_text = "\n".join(
    f"- {item['oasis_username']}: {item['content'][:100]}"
    for item in feed_items
) if feed_items else "（暫無帖文）"
```

Pass `feed_text` to both prompt templates as `{feed_context}`.

- [ ] **Step 4: Add {feed_context} to both prompt templates**

In `decision_prompts.py`:
```python
FEED_CONTEXT_BLOCK = """
你最近睇到嘅帖文：
{feed_context}
"""
```

In `cognitive_agent_engine.py` `_build_deliberation_prompt()`, add a `feed_block` similar to the existing `memory_block`.

- [ ] **Step 5: Commit**

```bash
git add backend/app/services/feed_ranker.py backend/app/services/simulation_runner.py backend/prompts/decision_prompts.py backend/app/services/cognitive_agent_engine.py
git commit -m "feat: wire feed ranking into agent cognition loop"
```

---

## Task 8: True Bayesian Belief Update

**Files:**
- Modify: `backend/app/services/belief_system.py` (~L185-252)
- Modify: `backend/app/services/belief_propagation.py` (~L94-182)
- Create: `backend/tests/test_bayesian_update.py`

- [ ] **Step 1: Write failing tests for Bayesian update**

Create `backend/tests/test_bayesian_update.py`:

```python
import pytest
from backend.app.services.belief_system import BeliefSystem, Belief

@pytest.mark.unit
class TestBayesianUpdate:
    def test_confirming_evidence_increases_belief(self):
        bs = BeliefSystem()
        belief = Belief(topic="economy", stance=0.3, confidence=0.5, evidence_count=0)
        # Positive evidence aligned with positive stance
        updated = bs.bayesian_update(belief, evidence_stance=0.8, evidence_weight=0.6, openness=0.5)
        assert updated.stance > belief.stance

    def test_contradicting_evidence_decreases_belief(self):
        bs = BeliefSystem()
        belief = Belief(topic="economy", stance=0.3, confidence=0.5, evidence_count=0)
        updated = bs.bayesian_update(belief, evidence_stance=-0.8, evidence_weight=0.6, openness=0.5)
        assert updated.stance < belief.stance

    def test_clamp_prevents_certainty_lock(self):
        bs = BeliefSystem()
        belief = Belief(topic="economy", stance=0.95, confidence=0.9, evidence_count=10)
        updated = bs.bayesian_update(belief, evidence_stance=1.0, evidence_weight=1.0, openness=0.5)
        assert updated.stance <= 0.98

    def test_clamp_prevents_negative_certainty_lock(self):
        bs = BeliefSystem()
        belief = Belief(topic="economy", stance=-0.95, confidence=0.9, evidence_count=10)
        updated = bs.bayesian_update(belief, evidence_stance=-1.0, evidence_weight=1.0, openness=0.5)
        assert updated.stance >= -0.98

    def test_stance_to_prob_roundtrip(self):
        bs = BeliefSystem()
        for stance in [-0.9, -0.5, 0.0, 0.5, 0.9]:
            prob = bs._stance_to_prob(stance)
            assert 0.0 < prob < 1.0
            back = bs._prob_to_stance(prob)
            assert abs(back - stance) < 0.001

    def test_zero_evidence_weight_no_change(self):
        bs = BeliefSystem()
        belief = Belief(topic="economy", stance=0.3, confidence=0.5, evidence_count=0)
        updated = bs.bayesian_update(belief, evidence_stance=0.8, evidence_weight=0.0, openness=0.5)
        assert updated.stance == belief.stance

    def test_kg_scale_bayesian_update(self):
        """kg_driven mode uses [0,1] scale directly."""
        bs = BeliefSystem()
        prior = 0.6
        lr = 2.0  # evidence supports hypothesis
        posterior = bs._bayesian_core(prior, lr)
        expected = (0.6 * 2.0) / (0.6 * 2.0 + 0.4)  # = 0.75
        assert abs(posterior - expected) < 0.001
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd . && python -m pytest backend/tests/test_bayesian_update.py -v`
Expected: FAIL (bayesian_update, _stance_to_prob, _bayesian_core not defined)

- [ ] **Step 3: Implement Bayesian update in belief_system.py**

In `backend/app/services/belief_system.py`, add these methods to the `BeliefSystem` class:

```python
@staticmethod
def _stance_to_prob(stance: float) -> float:
    """Map [-1, +1] stance to (0, 1) probability."""
    return _clamp((stance + 1.0) / 2.0, 0.02, 0.98)

@staticmethod
def _prob_to_stance(prob: float) -> float:
    """Map (0, 1) probability back to [-1, +1] stance."""
    return _clamp(prob * 2.0 - 1.0, -0.98, 0.98)

@staticmethod
def _bayesian_core(prior: float, likelihood_ratio: float) -> float:
    """Core Bayes update on [0,1] probability scale.

    posterior = (prior × LR) / (prior × LR + (1 - prior))
    """
    prior = max(0.02, min(0.98, prior))
    if likelihood_ratio <= 0:
        return prior
    numerator = prior * likelihood_ratio
    denominator = numerator + (1.0 - prior)
    if denominator < 1e-9:
        return prior
    return max(0.02, min(0.98, numerator / denominator))

def compute_likelihood_ratio(
    self,
    evidence_stance: float,
    evidence_weight: float,
    belief_stance: float,
    confirmation_bias: float = 0.5,
) -> float:
    """Compute likelihood ratio from evidence characteristics.

    LR > 1 means evidence supports current belief direction.
    LR < 1 means evidence contradicts.
    """
    if evidence_weight < 1e-9:
        return 1.0  # no evidence → no update
    base_lr = 1.0 + abs(evidence_stance) * evidence_weight
    same_direction = (evidence_stance >= 0) == (belief_stance >= 0)
    if same_direction:
        return base_lr * (1.0 + confirmation_bias * 0.3)
    else:
        return 1.0 / (base_lr * (1.0 - confirmation_bias * 0.3))

def bayesian_update(
    self,
    belief: "Belief",
    evidence_stance: float,
    evidence_weight: float,
    openness: float,
) -> "Belief":
    """True Bayesian belief update on [-1, +1] stance scale.

    Transforms stance → probability, applies Bayes, transforms back.
    """
    if evidence_weight < 1e-9:
        return belief

    lr = self.compute_likelihood_ratio(
        evidence_stance, evidence_weight, belief.stance,
        confirmation_bias=max(0.0, 1.0 - openness),
    )
    prob = self._stance_to_prob(belief.stance)
    posterior_prob = self._bayesian_core(prob, lr)
    new_stance = self._prob_to_stance(posterior_prob)

    # Update confidence based on evidence weight
    same_direction = (evidence_stance >= 0) == (belief.stance >= 0)
    if same_direction:
        new_confidence = min(1.0, belief.confidence + self.CONFIDENCE_INCREMENT * evidence_weight)
    else:
        reduction = self.CONFIDENCE_INCREMENT * evidence_weight * self.CONFIDENCE_DECREMENT_FACTOR
        new_confidence = max(self._CONFIDENCE_FLOOR, belief.confidence - reduction)

    return replace(
        belief,
        stance=round(new_stance, 4),
        confidence=round(new_confidence, 4),
        evidence_count=belief.evidence_count + 1,
    )
```

- [ ] **Step 4: Replace old update_belief calls with bayesian_update**

In `belief_system.py`, rename the old `update_belief` to `update_belief_legacy` and make `bayesian_update` the primary method. Update all callers in `simulation_runner.py` that call `update_belief` to call `bayesian_update`.

- [ ] **Step 5: Update belief_propagation.py to use bayesian_core on [0,1] scale**

In `backend/app/services/belief_propagation.py`, the `propagate()` method (~L94) uses linear delta. Replace with:

```python
from backend.app.services.belief_system import BeliefSystem

_bs = BeliefSystem()

# In propagate(), replace linear update with:
lr = _bs.compute_likelihood_ratio(
    evidence_stance=raw_delta,  # event delta as evidence direction
    evidence_weight=credibility * susceptibility,
    belief_stance=current * 2.0 - 1.0,  # convert [0,1] to [-1,1] for LR calc
    confirmation_bias=fingerprint.confirmation_bias,
)
new_belief = _bs._bayesian_core(current, lr)
```

- [ ] **Step 6: Run tests to verify they pass**

Run: `cd . && python -m pytest backend/tests/test_bayesian_update.py -v`
Expected: ALL PASS

- [ ] **Step 7: Commit**

```bash
git add backend/app/services/belief_system.py backend/app/services/belief_propagation.py backend/tests/test_bayesian_update.py
git commit -m "feat: implement true Bayesian belief update with dual-scale support"
```

---

## Task 9: Debate Delta → DB Persistence

**Files:**
- Modify: `backend/app/services/simulation_runner.py` (~L1891-1905)

- [ ] **Step 1: Add DB persistence after existing in-memory writeback**

In `simulation_runner.py`, after the existing in-memory debate writeback (~L1905), add:

```python
# Persist debate-updated beliefs to DB
debate_belief_rows = []
for agent_id, topic_deltas in deltas.items():
    for topic in topic_deltas:
        new_val = kg_state.agent_beliefs.get(agent_id, {}).get(topic)
        if new_val is not None:
            debate_belief_rows.append((
                session_id, agent_id, topic, new_val,
                0.5, 0, round_num,  # confidence, evidence_count defaults
            ))
if debate_belief_rows:
    await db.executemany(
        """INSERT OR REPLACE INTO belief_states
           (session_id, agent_id, topic, stance,
            confidence, evidence_count, round_number)
           VALUES (?, ?, ?, ?, ?, ?, ?)""",
        debate_belief_rows,
    )
```

- [ ] **Step 2: Commit**

```bash
git add backend/app/services/simulation_runner.py
git commit -m "feat: persist debate belief deltas to belief_states DB table"
```

---

## Task 10: Relationship → Behavior Feedback

**Files:**
- Modify: `backend/app/services/relationship_lifecycle.py` (~L165-182)
- Modify: `backend/app/services/emotional_engine.py` (~L97-198)
- Modify: `backend/prompts/decision_prompts.py`
- Modify: `backend/app/services/cognitive_agent_engine.py`
- Modify: `backend/app/services/simulation_runner.py`

- [ ] **Step 1: Add Gottman dissolution trigger**

In `backend/app/services/relationship_lifecycle.py`, find the DISSOLVED condition (~L165). Change from:

```python
if (
    state.commitment < _DISSOLVED_COMMITMENT_MAX
    and state.trust < _DISSOLVED_TRUST_MAX
):
```

to:

```python
gottman_sum = sum(state.gottman_scores.values()) if hasattr(state, 'gottman_scores') and state.gottman_scores else 0.0
gottman_ratio = gottman_sum / 4.0  # normalize to [0,1]
if (
    gottman_ratio > 0.8
    or (state.commitment < _DISSOLVED_COMMITMENT_MAX and state.trust < _DISSOLVED_TRUST_MAX)
):
```

- [ ] **Step 2: Add trust context to decision prompts**

In `simulation_runner.py`, before decision step, query top trusted/distrusted agents:

```python
cursor = await db.execute(
    """SELECT agent_b_id, trust_score FROM agent_relationships
       WHERE session_id = ? AND agent_a_id = ?
       ORDER BY trust_score DESC LIMIT 3""",
    (session_id, agent["id"]),
)
trusted = [dict(r) for r in await cursor.fetchall()]

cursor = await db.execute(
    """SELECT agent_b_id, trust_score FROM agent_relationships
       WHERE session_id = ? AND agent_a_id = ?
       ORDER BY trust_score ASC LIMIT 3""",
    (session_id, agent["id"]),
)
distrusted = [dict(r) for r in await cursor.fetchall()]
```

Pass into prompt as `{trusted_agents}` / `{distrusted_agents}`.

- [ ] **Step 3: Add relationship crisis → emotion impact**

In `backend/app/services/emotional_engine.py`, add a parameter to `update_state()`:

```python
relationship_crisis: bool = False,
```

And in the valence calculation, add:

```python
if relationship_crisis:
    new_valence = _clamp(new_valence - 0.1, -1.0, 1.0)
    new_arousal = _clamp(new_arousal + 0.15, 0.0, 1.0)
```

- [ ] **Step 4: Commit**

```bash
git add backend/app/services/relationship_lifecycle.py backend/app/services/emotional_engine.py backend/prompts/decision_prompts.py backend/app/services/cognitive_agent_engine.py backend/app/services/simulation_runner.py
git commit -m "feat: wire relationship engine into decisions and emotions"
```

---

## Task 11: Shock → MacroController

**Files:**
- Modify: `backend/app/api/simulation.py` (shock endpoint ~L1517-1568)
- Modify: `backend/app/services/macro_shocks.py`

- [ ] **Step 1: Add generic apply_macro_effects to macro_shocks.py**

In `backend/app/services/macro_shocks.py`, add:

```python
async def apply_macro_effects(
    session_id: str, effects: dict[str, float], db: Any,
) -> None:
    """Apply arbitrary macro parameter changes from a God Mode shock."""
    cursor = await db.execute(
        "SELECT * FROM macro_scenarios WHERE session_id = ? ORDER BY round_number DESC LIMIT 1",
        (session_id,),
    )
    row = await cursor.fetchone()
    if not row:
        return
    updates = {}
    for param, delta in effects.items():
        current = row[param] if param in row.keys() else None
        if current is not None:
            updates[param] = current + delta
    if updates:
        set_clause = ", ".join(f"{k} = ?" for k in updates)
        await db.execute(
            f"UPDATE macro_scenarios SET {set_clause} WHERE session_id = ? AND round_number = ?",
            (*updates.values(), session_id, row["round_number"]),
        )
        await db.commit()
```

- [ ] **Step 2: Wire shock endpoint to macro_effects**

In `backend/app/api/simulation.py`, find the shock injection endpoint (~L1517). After the existing post creation, add:

```python
if shock.macro_effects:
    from backend.app.services.macro_shocks import apply_macro_effects
    db = await get_db()
    await apply_macro_effects(session_id, shock.macro_effects, db)
```

- [ ] **Step 3: Commit**

```bash
git add backend/app/api/simulation.py backend/app/services/macro_shocks.py
git commit -m "feat: wire shock macro_effects to MacroController state"
```

---

## Task 12: Branch Deep Copy → Full State

**Files:**
- Modify: `backend/app/api/simulation_branches.py` (~L70-129)
- Modify: `backend/app/services/swarm_ensemble.py` (~L274-345)
- Modify: `backend/app/services/auto_fork_service.py` (~L170-211)

- [ ] **Step 1: Fix swarm_ensemble.py kg_nodes column names**

In `backend/app/services/swarm_ensemble.py`, find the kg_nodes copy (~L339-345). Fix column names to match schema.sql:

Replace `node_type` with `entity_type` and `source` with `properties` (verify exact column names against schema.sql first).

- [ ] **Step 2: Add missing tables to simulation_branches.py**

In `backend/app/api/simulation_branches.py`, after the existing copy blocks (~L129), add:

```python
# Copy belief_states
await db.execute(
    """INSERT INTO belief_states (session_id, agent_id, topic, stance, confidence, evidence_count, round_number)
       SELECT ?, agent_id, topic, stance, confidence, evidence_count, round_number
       FROM belief_states WHERE session_id = ? AND round_number <= ?""",
    (branch_id, session_id, fork_round),
)
# Copy emotional_states
await db.execute(
    """INSERT INTO emotional_states (session_id, agent_id, valence, arousal, dominance, round_number)
       SELECT ?, agent_id, valence, arousal, dominance, round_number
       FROM emotional_states WHERE session_id = ? AND round_number <= ?""",
    (branch_id, session_id, fork_round),
)
# Copy agent_relationships
await db.execute(
    """INSERT INTO agent_relationships (session_id, agent_a_id, agent_b_id, trust_score, relationship_type)
       SELECT ?, agent_a_id, agent_b_id, trust_score, relationship_type
       FROM agent_relationships WHERE session_id = ?""",
    (branch_id, session_id),
)
# Copy kg_edges
await db.execute(
    """INSERT INTO kg_edges (session_id, source_id, target_id, relation_type, weight, properties)
       SELECT ?, source_id, target_id, relation_type, weight, properties
       FROM kg_edges WHERE session_id = ?""",
    (branch_id, session_id),
)
# Copy cognitive_dissonance
await db.execute(
    """INSERT INTO cognitive_dissonance (session_id, agent_id, round_number, conflict_score, resolution_strategy)
       SELECT ?, agent_id, round_number, conflict_score, resolution_strategy
       FROM cognitive_dissonance WHERE session_id = ? AND round_number <= ?""",
    (branch_id, session_id, fork_round),
)
```

- [ ] **Step 3: Add same tables to swarm_ensemble.py and auto_fork_service.py**

Replicate the same INSERT...SELECT pattern in both files' branch creation methods. Use the same column names (verify against schema.sql before inserting).

- [ ] **Step 4: Commit**

```bash
git add backend/app/api/simulation_branches.py backend/app/services/swarm_ensemble.py backend/app/services/auto_fork_service.py
git commit -m "feat: expand branch deep copy to all dynamic state tables"
```

---

## Task 13: Batch Test Fixes

**Files:**
- Modify: Multiple test files across `backend/tests/`
- Create: All new test files listed in File Map

- [ ] **Step 1: Run full test suite to identify breakage**

Run: `cd . && python -m pytest backend/tests/ -x --tb=short 2>&1 | head -100`

Record all failures.

- [ ] **Step 2: Fix tier-related test assertions**

Search for all tests referencing `tier1_agents`, `tier`, `_assign_tiers`, `LIMIT 30`:

Run: `grep -rn "tier1_agents\|tier.*agent\|LIMIT 30\|_assign_tier" backend/tests/ --include="*.py"`

Update each to use `stakeholder_agents` and the new activation model.

- [ ] **Step 3: Fix belief_system test assertions**

Tests that assert on old `update_belief` linear behavior need updating for Bayesian behavior. The direction of change should be the same, but magnitudes will differ.

- [ ] **Step 4: Create remaining integration tests**

Create all test files listed in the File Map that weren't created in earlier tasks:
- `test_stochastic_activation.py`
- `test_feed_cognition.py`
- `test_debate_db_persist.py`
- `test_branch_full_copy.py`
- `test_shock_macro.py`
- `test_relationship_dissolution.py`

Each test should follow the pattern: set up DB state → call the function → assert expected outcome.

- [ ] **Step 5: Run full test suite and confirm green**

Run: `cd . && python -m pytest backend/tests/ -v --tb=short`
Expected: ALL PASS

- [ ] **Step 6: Commit**

```bash
git add backend/tests/
git commit -m "test: fix broken tests and add integration tests for wiring upgrade"
```

---

## Task 14: README Alignment

**Files:**
- Modify: `README.md`

- [ ] **Step 1: Update misleading claims**

Apply the following changes:

| Find | Replace with |
|------|-------------|
| `貝葉斯信念更新` | Keep as-is (now truly Bayesian) |
| `100 至 50,000 個 AI 代理人` | `100 至 50,000 個 AI 代理人，每輪由 stochastic activation 決定邊啲執行 LLM 推理` |
| `30 秒內啟動` | `1-3 分鐘內啟動（視代理人數量）` |
| `對比真實歷史數據的回溯驗證` | `對比真實歷史數據的回溯驗證（驗證框架已建立，持續累積歷史比對數據）` |

- [ ] **Step 2: Commit**

```bash
git add README.md
git commit -m "docs: align README claims with actual implementation"
```
