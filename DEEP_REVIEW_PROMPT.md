# MurmuraScope Deep Architecture Review Prompt

> Feed this prompt to any frontier LLM (Claude Opus, GPT-4o, Gemini Ultra) for a rigorous,
> code-grounded evaluation. All claims below are verified against source code as of 2026-03-22.

---

## System Prompt

You are a panel of three domain experts conducting a joint deep review:

1. **Prof. A** — Computational Social Science, specialising in Agent-Based Modelling (ABM), emergence detection, and opinion dynamics (Hegselmann-Krause, Deffuant, Sznajd models).
2. **Prof. B** — Quantitative Finance & Econometrics, former research director at a central bank (HKMA-equivalent), specialising in time-series forecasting, stress testing (Basel III/IV), and financial risk modelling.
3. **Prof. C** — AI Systems Engineering, specialising in LLM-agent architectures, structured concurrency, cost-aware inference pipelines, and distributed simulation at scale.

Your task is to evaluate **MurmuraScope** — a hybrid LLM-Econometric prediction engine that simulates collective human behaviour under macro shocks — across **7 dimensions**. Score each dimension 1–10 with detailed justification. Then produce a final verdict.

---

## System Under Review: MurmuraScope

### Overview

MurmuraScope is a universal prediction engine combining multi-agent simulation (50–50,000 agents), knowledge graph reasoning, LLM-driven deliberation, and traditional econometric validation. It operates in two modes:

- **hk_demographic**: Hong Kong socioeconomic simulation with census-derived agents, hardcoded decision types, and HK-specific macro indicators.
- **kg_driven** (universal): Any seed text (geopolitics, fiction, corporate strategy) → automatic entity extraction → KG → LLM-generated agents, decision spaces, metrics, and shocks. No manual domain configuration required.

### Tech Stack
- FastAPI (Python 3.11), aiosqlite, Pydantic V2 (frozen models)
- Vue 3 + Vite + TypeScript (gradual migration)
- LLMs: OpenRouter (agents), Google Gemini (reports); dual-model routing (stakeholder → strong model, background → lite model)
- OASIS framework (subprocess IPC via JSONL stdout)
- SQLite WAL (55 tables), LanceDB (384-dim multilingual embeddings)
- 19 API routers, 140+ endpoints, WebSocket streaming
- 149 test files (~2,625 unit + ~134 integration)

---

## Verified Architecture Inventory (Code-Grounded)

### A. Agent Cognition & Decision Pipeline

| Component | Implementation | Key Constants |
|-----------|---------------|---------------|
| **CognitiveAgentEngine** | Full LLM deliberation (temp 0.5, max 1024 tokens) → `DeliberationResult` with decision, reasoning, belief_updates (clamped ±0.3), stance_statement, topic_tags (≤4), emotional_reaction | — |
| **Risk Appetite** | Smooth sigmoid×tanh continuous formula: `amplifier = 1/(1+exp(-12(arousal-0.5)))`, `direction = tanh(2×valence)`, `raw = 0.5 + 0.4 × amplifier × direction`, clamped [0.1, 0.9]. No step function. | steepness=-12, scale=0.4 |
| **Prompt Enrichment** | Persona + goals + stance axes + emotional state + risk appetite label + attachment style + relationship block (defensive/cooperative/neutral disposition) + memory block + feed context + trust context + strategic context | — |
| **KGAgentFactory** | Two-stage LLM pipeline: (1) filter eligible entities → (2) generate UniversalAgentProfile with Big Five personality, goals, relationships. Then pure-function attachment style inference from Big Five traits (anxious/avoidant/disorganized/secure). | `_AGENT_ELIGIBLE_TYPES`: 11 entity types |
| **ScenarioGenerator** | Single LLM call (temp 0.3, max 4096 tokens) → decision_types (max 20), metrics (max 15), shock_types (max 15), impact_rules, implied_actors, stakeholder_entity_types | — |
| **Stochastic Activation** | No fixed tier budget. Each round samples agents by `activity_level` [0,1]; stakeholders floor 0.8. ALL activated agents use LLM (stakeholders → strong model; background → lite model). | floor=0.8 |

### B. Belief Dynamics & Social Interaction

| Component | Implementation | Key Constants |
|-----------|---------------|---------------|
| **BeliefSystem** | True Bayesian: stance ↔ probability dual-scale transform (`_stance_to_prob` / `_prob_to_stance`, clamped [0.02, 0.98]). `LR = 1 + |evidence_stance| × evidence_weight`. Confirmation bias: same-direction × `1 + (bias × 0.3)`; opposite-direction × `1 - bias_factor`. | CONFIRMATION_BIAS_BOOST=1.3, RESIST=0.6, CONFIDENCE_FLOOR=0.1 |
| **BeliefPropagationEngine** | Sequential Bayesian update per event (impact × credibility × susceptibility → LR → `_bayesian_core`). Blends with Hegselmann-Krause faction peer pressure: effective ε = `HC_EPSILON × (0.5 + 0.5 × openness)`. 1-hop cascade: shift threshold >0.1, cascade factor 0.3, leadership boost ±0.5 scaled by normalised degree. | HC_EPSILON=0.4, CASCADE_FACTOR=0.3, LEADERSHIP_BOOST=0.5 |
| **ConsensusDebateEngine** | Triggers every 3 rounds on divergent topics (std ≥ 0.15). Cross-faction tercile pair sampling (max 15 pairs, max 5 topics). LLM debate A→B→response. Per-exchange delta clamped ±0.15; per-agent-topic-round total clamped ±0.20. | DIVERGENCE_THRESHOLD=0.15, MAX_DELTA=0.20 |
| **RelationshipEngine** | Sternberg triangular (intimacy/passion/commitment) + Rusbult investment model (satisfaction/alternatives/investment) + Gottman Four Horsemen (contempt 1.5×, stonewalling 0.9×, criticism 0.8×, defensiveness 0.5×). Exponential decay calibrated to half-lives: intimacy ~5y, passion ~18mo, commitment ~10y, trust ~2y. Attachment modulation (anxious amplifies, avoidant dampens). | ROUND_DURATION_DAYS=7 |

### C. Emergence Detection & Quantification

| Component | Implementation | Key Constants |
|-----------|---------------|---------------|
| **EmergenceMetricsCalculator** | Time-Delayed Mutual Information (TDMI) using scikit-learn Kraskov KNN estimator (k=5). Lags (1, 3, 5). Minimum 30 samples. Persisted to `emergence_metrics` table. | EMERGENCE_THRESHOLD=0.02 nats, MIN_SAMPLES=30 |
| **FactionMapper** | Louvain community detection on belief similarity graph. | — |
| **TippingPointDetector** | Jensen-Shannon Divergence (JSD) between consecutive rounds' belief distributions. | JSD_THRESHOLD=0.15 |

### D. Structured Concurrency (Simulation Hooks)

The simulation loop uses a 3-group structured concurrency pattern per round:

- **Pre-Group-1:** Feed ranking; kg_driven: world event generation (LLM or lite rule-based)
- **Group 1 (parallel):** Memory retrieval, trust updates, emotional state, relationship states
- **Group 2 (sequential):** Decisions, side effects, belief update, consumption; kg_driven adds: strategic planning + stochastic LLM deliberation (all activated agents) + consensus debate (every 3 rounds) + belief propagation
- **Group 3 (periodic):** Echo chambers (3), network evolution (3), virality (3), macro feedback (5), KG evolution (3), polarisation (5), TDMI (5); kg_driven adds: faction + tipping (3), relationship lifecycle (3)

Fire-and-forget with `asyncio.wait_for(timeout_s=60)` (LLM-heavy: 90s).

### E. Probabilistic Forecasting & Ensemble Methods

| Component | Implementation | Key Constants |
|-----------|---------------|---------------|
| **MonteCarloEngine** | Latin Hypercube Sampling via `scipy.stats.qmc.LatinHypercube` + t-Copula (df=4, Cholesky decomposition). Correlated macro variables transformed through copula; independent variables via raw LHS. `run_mini()` for quick 10-trial ensemble on 4 core metrics. | Trial cap: 2,000 (HK mode); sampling_method="lhs_t_copula" |
| **SwarmEnsemble** | Phase A: 1 full LLM simulation (baseline). Phase B: N lite-ensemble replicas (rule-based hooks, different random seeds). 8-table deep state copy at fork_round. Outcome classification: disruption_polarized / disruption_converged / fragmentation / consensus / stalemate. Belief cloud: p25/median/p75 per topic. Wilson score CIs. | MAX_REPLICAS=500, MAX_CONCURRENT=3, high_polar>0.25, dominant>0.6 |
| **MultiRunOrchestrator** | Zero-LLM stochastic ensemble. t-distribution sampling (df=5). Wilson score 95% CIs (z=1.96). | HARD_CAP=50,000 trials |
| **AutoForkService** | Fires when JSD ≥ 0.225 (1.5× base threshold). Adaptive budget: `min(5, max(2, round_count//10))`. Counterfactual nudge strategies: polarize→compress (0.5+dev×0.5), converge→amplify (0.5+dev×1.5), split→reverse (0.5-dev). Creates 2 branch sessions (natural + nudged). | JSD_STRONG=0.225, MIN_FORKS=2, MAX_FORKS=5 |

### F. Validation & Econometric Rigour

| Component | Status | Implementation Details |
|-----------|--------|----------------------|
| **Walk-Forward Backtesting** | ✅ Implemented | `kfold_validate()` with `_FoldScopedCoefficients` preventing look-ahead bias. Fold 0 = burn-in skipped. Drift computed from training window only. |
| **Composite Validation Score** | ✅ Implemented | `30% directional_accuracy + 30% |pearson_r| + 20% (1 - min(MAPE,1)) + 20% max(0, 1 - brier_score/0.25)`. Grades: A≥0.80, B≥0.65, C≥0.50, D≥0.35, F<0.35. |
| **LHS + t-Copula Monte Carlo** | ✅ Implemented | See Section E above. |
| **VAR Model** | ⚠️ Partial | 3 variable groups (property, labour, market). AIC lag selection (max 4). VECM imported but integration incomplete. |
| **Sobol Sensitivity Indices** | ✅ Implemented | S₁ (first-order) and Sₜ (total-order) via SALib. 5 calibration parameters × 5 macro metrics. |
| **Structural Break Detection** | ⚠️ Partial | CUSUM-based (`recursive_olsresiduals`) + variance-ratio fallback. Not full Bai-Perron. |
| **ADF/KPSS Stationarity Tests** | ❌ Not implemented | Referenced in documentation but absent from service code. |
| **Granger Causality** | ❌ Not implemented | No pre-whitening, no multiple-testing correction. |
| **VECM Co-integration** | ❌ Not implemented | Johansen test and VECM referenced/imported but not wired into production. |
| **CRPS** | ❌ Not implemented | Brier score used instead of distributional evaluation. |
| **ARCH/GARCH** | ❌ Not implemented | No heteroscedasticity testing or volatility clustering model. |
| **Bai-Perron** | ❌ Not implemented | CUSUM used as alternative. |

### G. Lite Hooks (Rule-Based Fallbacks)

Used **exclusively** in SwarmEnsemble Phase B replicas (lite_ensemble=True). NOT used in the primary simulation path.

| Function | Algorithm |
|----------|-----------|
| `generate_lite_events()` | Mean-reverting stochastic: extreme stances revert with 50%+75%×deviation probability; impact = base_delta + gauss(0, 0.08); shock type amplifies 2.5×. Event types weighted: official 35%, rumor 30%, grassroots 20%, shock 15%. |
| `deliberate_lite()` | Reactivity = `0.5 + (openness-0.5)×0.6`. Confirmation bias per event. Decision threshold: |shift| > 0.08 → escalate/de-escalate, else maintain. |
| `debate_lite()` | Hegselmann-Krause bounded confidence (default radius 0.55). Personality modulates magnitude (openness boosts, neuroticism dampens). |

### H. Cost & Resource Management

| Feature | Implementation |
|---------|---------------|
| **CostTracker** | Per-session async accumulation. Soft budget $5 (WARNING), hard cap $10 (pauses simulation, WebSocket `cost_pause` event). Auto-resume after 30 min. Manual resume via `POST /{id}/resume`. |
| **Dual-model routing** | `get_agent_model(is_stakeholder=True)` → AGENT_LLM_MODEL (strong); `False` → AGENT_LLM_MODEL_LITE (cheaper, falls back to strong if unset). |
| **Subprocess watchdog** | Kills OASIS subprocess if RAM > SUBPROCESS_MEMORY_LIMIT_MB (default 2048). Orphan reaping on startup. |
| **SurrogateIntegration** | `auto_train_surrogate()` with 5s timeout + graceful fallback. LogisticRegression on belief→decision pairs (min 20 training rows). |

---

## Evaluation Dimensions (Score 1–10 Each)

### Dimension 1: Agent Heterogeneity & Cognitive Realism (Prof. A)

Evaluate whether the agent model produces meaningfully different behavioural trajectories under identical stimuli:

- How does the Big Five → attachment style → risk appetite → deliberation pipeline compare to state-of-the-art computational social science (Epstein 2006, Conte & Paolucci 2014)?
- Is the sigmoid×tanh risk appetite formula psychologically grounded? Does steepness=-12 create a near-binary switch despite being technically continuous?
- The Bayesian belief update uses confirmation bias modulation via openness. Is the LR formula `1 + |evidence| × weight × (1 + bias×0.3)` a defensible approximation of Bayesian cognition, or an ad-hoc hack?
- Hegselmann-Krause bounded confidence with openness-scaled ε: does widening the confidence radius for open agents produce empirically validated polarisation dynamics?

### Dimension 2: Emergence Authenticity (Prof. A)

Evaluate whether the system proves — not merely claims — emergent phenomena:

- TDMI with Kraskov KNN (k=5): is this the right estimator for discrete-time agent belief trajectories? What are the bias/variance tradeoffs at 30 minimum samples?
- The 0.02 nats threshold for emergence: how was this calibrated? Is it defensible against null-model comparison?
- JSD for tipping point detection at 0.15: is this threshold empirically justified or arbitrary?
- Does the combination of TDMI + JSD + Louvain factions constitute a sufficient emergence detection suite, or are critical methods missing (e.g., transfer entropy, Granger-in-information-space, recurrence quantification)?

### Dimension 3: Predictive Authenticity & Causal Tracing (Prof. B)

Evaluate whether the system produces forecasts with genuine predictive value, not merely plausible narratives:

- Walk-forward backtesting with FoldScopedCoefficients: is this sufficient to prevent overfitting, or does the autoregressive drift model (value × (1 + drift)) need more sophisticated basis functions?
- Composite validation score (30/30/20/20): are these weights empirically justified? Is the Brier skill score denominator (0.25) the correct uninformative baseline for this domain?
- The system has LHS + t-Copula but caps at 2,000 trials. For fat-tailed financial distributions, is this sufficient for p99 estimation?
- Can the engine causally trace a macro-level shift (e.g., HSI crash) back to specific micro-level agent deliberations, topic tags, and belief cascades? How robust is this causal chain?

### Dimension 4: Econometric Rigour Gaps (Prof. B)

Evaluate the impact of missing statistical infrastructure:

- **No ADF/KPSS**: Without stationarity testing, how can the VAR model be trusted? Is spurious regression a live risk?
- **No VECM**: The system detects co-integration (Johansen imported) but doesn't act on it. What forecast quality is lost?
- **No ARCH/GARCH**: Financial returns exhibit volatility clustering. Without heteroscedasticity modelling, how unreliable are the Monte Carlo confidence intervals during crisis periods?
- **No CRPS**: The system evaluates point forecasts (MAPE) and binary outcomes (Brier) but not distributional forecasts. How does this affect credibility for probabilistic prediction claims?
- **No Granger causality**: The system claims causal inference through agent deliberation traces, but has no statistical causality test. Is the LLM-based causal narrative a substitute or a complement?
- **Structural breaks via CUSUM only**: Without Bai-Perron's multiple-break detection, could the system miss regime transitions in training data?

### Dimension 5: Scalability & Systems Architecture (Prof. C)

Evaluate the engineering ceiling of the current architecture:

- SQLite WAL + aiosqlite: what is the realistic agent-count ceiling before write contention becomes the bottleneck? Is the 50,000-agent claim achievable?
- OASIS subprocess IPC via JSONL stdout: what are the latency/throughput characteristics? How does this compare to shared-memory or gRPC approaches?
- Structured concurrency (3-group hooks with asyncio.wait_for timeouts): is this a robust orchestration pattern, or does it risk silent data loss on timeout?
- SwarmEnsemble Phase B runs 500 replicas with MAX_CONCURRENT=3. What is the total wall-clock time for a DEEP preset (500 agents, 30 rounds)?
- The dual-model routing (stakeholder vs background) saves cost but creates a fidelity gradient. Does this gradient introduce systematic bias in ensemble results?

### Dimension 6: Novel Contributions vs Prior Art (All Professors)

Compare MurmuraScope against these baselines on each specific feature:

| Feature | MurmuraScope | Stanford Generative Agents (2023) | MiroFish (2024) | Simudyne (commercial) | ChatDev / MetaGPT |
|---------|-------------|----------------------------------|-----------------|----------------------|-------------------|
| Agent cognitive model | ? | ? | ? | ? | ? |
| Belief update mechanism | ? | ? | ? | ? | ? |
| Emergence detection | ? | ? | ? | ? | ? |
| Probabilistic forecasting | ? | ? | ? | ? | ? |
| Causal tracing | ? | ? | ? | ? | ? |
| Temporal branching | ? | ? | ? | ? | ? |
| Validation methodology | ? | ? | ? | ? | ? |
| Scale ceiling | ? | ? | ? | ? | ? |

Fill each cell with a 1-sentence assessment and a score (1–5).

### Dimension 7: Publication & Commercialisation Readiness (All Professors)

- **For JASSS / Computational Economics / AAMAS**: What is the single strongest novel contribution? What is the single biggest methodological gap that would cause desk rejection?
- **For commercial deployment** (policy think tanks, property developers, hedge funds): Rank readiness 1–5 for each client type. What is the minimum viable improvement for each?
- **For regulatory stress testing** (Basel III/IV, HKMA): What critical infrastructure is missing?

---

## Required Output Format

1. **Scoring Matrix**: 7 dimensions × 3 professors, with 1-sentence justification per cell.
2. **Feature Comparison Table**: Dimension 6 filled completely.
3. **Gap Priority Matrix**: Each missing feature (ADF/KPSS, VECM, ARCH/GARCH, CRPS, Granger, Bai-Perron) scored by (a) publication impact, (b) commercial impact, (c) implementation effort (1-5 each).
4. **Architectural Bottleneck Analysis**: Identify the exact point where the current architecture fails at scale (agent count, trial count, concurrent users).
5. **Final Verdict**: One of:
   - **Tier 1 — Scientific Oracle**: Publishable in top venues, commercially deployable with minor polish.
   - **Tier 2 — Advanced Research Prototype**: Publishable with significant additions, commercial demo-ready.
   - **Tier 3 — Sophisticated Toy**: Impressive engineering but lacks statistical/methodological rigour for serious use.
6. **Top 5 Highest-ROI Improvements**: Ordered by (publication_impact × commercial_impact) / implementation_effort.
