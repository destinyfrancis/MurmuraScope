-- HKSimEngine Database Schema
-- SQLite with WAL mode for concurrent reads

PRAGMA journal_mode=WAL;
PRAGMA foreign_keys=ON;

-- ============================================================
-- hk_data_snapshots: 所有公開數據嘅時間序列快照
-- ============================================================
CREATE TABLE IF NOT EXISTS hk_data_snapshots (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    category TEXT NOT NULL,
    metric TEXT NOT NULL,
    value REAL NOT NULL,
    unit TEXT,
    period TEXT NOT NULL,
    source TEXT NOT NULL,
    source_url TEXT,
    created_at TEXT DEFAULT (datetime('now'))
);
CREATE INDEX IF NOT EXISTS idx_snapshot_cat_metric ON hk_data_snapshots(category, metric);
CREATE INDEX IF NOT EXISTS idx_snapshot_period ON hk_data_snapshots(period);

-- ============================================================
-- population_distributions: Census probability tables
-- ============================================================
CREATE TABLE IF NOT EXISTS population_distributions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    category TEXT NOT NULL,
    dimension_1 TEXT NOT NULL,
    dimension_2 TEXT,
    dimension_3 TEXT,
    count INTEGER NOT NULL,
    probability REAL NOT NULL,
    source_year INTEGER NOT NULL,
    source_dataset TEXT NOT NULL,
    created_at TEXT DEFAULT (datetime('now'))
);
CREATE INDEX IF NOT EXISTS idx_pop_category ON population_distributions(category);

-- ============================================================
-- knowledge_graph_nodes: 本地 GraphRAG（代替 Zep Cloud）
-- ============================================================
CREATE TABLE IF NOT EXISTS kg_nodes (
    id TEXT PRIMARY KEY,
    session_id TEXT NOT NULL,
    entity_type TEXT NOT NULL,
    title TEXT NOT NULL,
    description TEXT,
    properties TEXT,
    created_at TEXT DEFAULT (datetime('now'))
);
CREATE INDEX IF NOT EXISTS idx_kg_session ON kg_nodes(session_id);
CREATE INDEX IF NOT EXISTS idx_kg_type ON kg_nodes(entity_type);

CREATE TABLE IF NOT EXISTS kg_edges (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id TEXT NOT NULL,
    source_id TEXT NOT NULL REFERENCES kg_nodes(id),
    target_id TEXT NOT NULL REFERENCES kg_nodes(id),
    relation_type TEXT NOT NULL,
    description TEXT,
    weight REAL DEFAULT 1.0,
    created_at TEXT DEFAULT (datetime('now'))
);
CREATE INDEX IF NOT EXISTS idx_edge_session ON kg_edges(session_id);
CREATE INDEX IF NOT EXISTS idx_edge_source ON kg_edges(source_id);
CREATE INDEX IF NOT EXISTS idx_edge_target ON kg_edges(target_id);

CREATE TABLE IF NOT EXISTS kg_communities (
    id TEXT PRIMARY KEY,
    session_id TEXT NOT NULL,
    title TEXT NOT NULL,
    summary TEXT,
    member_ids TEXT NOT NULL,
    created_at TEXT DEFAULT (datetime('now'))
);
CREATE INDEX IF NOT EXISTS idx_community_session ON kg_communities(session_id);

-- ============================================================
-- macro_scenarios
-- ============================================================
CREATE TABLE IF NOT EXISTS macro_scenarios (
    id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    data_snapshot TEXT NOT NULL,
    description TEXT,
    is_baseline BOOLEAN DEFAULT 0,
    created_at TEXT DEFAULT (datetime('now'))
);

-- ============================================================
-- simulation_sessions
-- ============================================================
CREATE TABLE IF NOT EXISTS simulation_sessions (
    id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    sim_mode TEXT NOT NULL,
    seed_text TEXT NOT NULL DEFAULT '',
    scenario_type TEXT,
    graph_id TEXT,
    agent_count INTEGER NOT NULL,
    round_count INTEGER NOT NULL,
    llm_provider TEXT NOT NULL,
    llm_model TEXT NOT NULL DEFAULT 'accounts/fireworks/models/minimax-m2p5',
    macro_scenario_id TEXT REFERENCES macro_scenarios(id),
    oasis_db_path TEXT NOT NULL DEFAULT '',
    -- Full request JSON blob; stores agent_csv_path, shocks, family_members, etc.
    config_json TEXT,
    -- Optional platform map JSON e.g. '{"twitter": true, "reddit": false}'
    platforms TEXT,
    status TEXT DEFAULT 'created',
    current_round INTEGER DEFAULT 0,
    total_tokens INTEGER DEFAULT 0,
    estimated_cost_usd REAL DEFAULT 0.0,
    error_message TEXT,
    started_at TEXT,
    completed_at TEXT,
    created_at TEXT DEFAULT (datetime('now'))
);
CREATE INDEX IF NOT EXISTS idx_session_status ON simulation_sessions(status);

-- ============================================================
-- agent_profiles
-- ============================================================
CREATE TABLE IF NOT EXISTS agent_profiles (
    id INTEGER PRIMARY KEY,
    session_id TEXT NOT NULL REFERENCES simulation_sessions(id),
    agent_type TEXT NOT NULL,
    age INTEGER NOT NULL,
    sex TEXT NOT NULL,
    district TEXT NOT NULL,
    occupation TEXT NOT NULL,
    income_bracket TEXT NOT NULL,
    education_level TEXT NOT NULL,
    marital_status TEXT NOT NULL,
    housing_type TEXT NOT NULL,
    openness REAL NOT NULL,
    conscientiousness REAL NOT NULL,
    extraversion REAL NOT NULL,
    agreeableness REAL NOT NULL,
    neuroticism REAL NOT NULL,
    monthly_income INTEGER,
    savings INTEGER,
    oasis_persona TEXT NOT NULL,
    oasis_username TEXT NOT NULL,
    created_at TEXT DEFAULT (datetime('now'))
);
CREATE INDEX IF NOT EXISTS idx_agent_session ON agent_profiles(session_id);
CREATE INDEX IF NOT EXISTS idx_agent_type ON agent_profiles(agent_type);

-- ============================================================
-- reports
-- ============================================================
CREATE TABLE IF NOT EXISTS reports (
    id TEXT PRIMARY KEY,
    session_id TEXT REFERENCES simulation_sessions(id),
    report_type TEXT NOT NULL,
    title TEXT NOT NULL,
    content_markdown TEXT NOT NULL,
    summary TEXT,
    key_findings TEXT,
    charts_data TEXT,
    agent_log TEXT,
    created_at TEXT DEFAULT (datetime('now'))
);
CREATE INDEX IF NOT EXISTS idx_report_session ON reports(session_id);

-- ============================================================
-- simulation_actions: 結構化行為日誌（#5）
-- ============================================================
CREATE TABLE IF NOT EXISTS simulation_actions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id TEXT NOT NULL,
    round_number INTEGER NOT NULL,
    agent_id INTEGER,
    oasis_username TEXT NOT NULL,
    action_type TEXT NOT NULL DEFAULT 'post',
    platform TEXT NOT NULL DEFAULT 'twitter',
    content TEXT NOT NULL,
    target_agent_username TEXT,
    sentiment TEXT NOT NULL DEFAULT 'neutral',
    topics TEXT DEFAULT '[]',
    post_id TEXT,
    created_at TEXT DEFAULT (datetime('now'))
);
CREATE INDEX IF NOT EXISTS idx_action_session_round ON simulation_actions(session_id, round_number);
CREATE INDEX IF NOT EXISTS idx_action_session_agent ON simulation_actions(session_id, agent_id);

-- Phase 17: Contagion tracking columns (added via ALTER TABLE at runtime)
-- parent_action_id INTEGER REFERENCES simulation_actions(id)
-- spread_depth INTEGER DEFAULT 0

-- Phase 17: Polarization snapshots
CREATE TABLE IF NOT EXISTS polarization_snapshots (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id TEXT NOT NULL,
    round_number INTEGER NOT NULL,
    polarization_index REAL NOT NULL,
    modularity REAL NOT NULL,
    opinion_variance REAL NOT NULL,
    cross_cluster_hostility REAL NOT NULL,
    cluster_stances_json TEXT NOT NULL DEFAULT '{}',
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(session_id, round_number)
);
CREATE INDEX IF NOT EXISTS idx_polar_session ON polarization_snapshots(session_id);

-- ============================================================
-- agent_memories: Agent 長期記憶（#1）
-- ============================================================
CREATE TABLE IF NOT EXISTS agent_memories (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id TEXT NOT NULL,
    agent_id INTEGER NOT NULL,
    round_number INTEGER NOT NULL,
    memory_text TEXT NOT NULL,
    salience_score REAL NOT NULL DEFAULT 1.0,
    memory_type TEXT NOT NULL DEFAULT 'observation',
    created_at TEXT DEFAULT (datetime('now'))
);
CREATE INDEX IF NOT EXISTS idx_memory_session_agent ON agent_memories(session_id, agent_id);
CREATE INDEX IF NOT EXISTS idx_memory_session_round ON agent_memories(session_id, round_number);

-- ============================================================
-- memory_triples: 代理記憶關係三元組（TKG）
-- ============================================================
CREATE TABLE IF NOT EXISTS memory_triples (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    memory_id INTEGER NOT NULL REFERENCES agent_memories(id) ON DELETE CASCADE,
    session_id TEXT NOT NULL,
    agent_id INTEGER NOT NULL,
    round_number INTEGER NOT NULL,
    subject TEXT NOT NULL,
    predicate TEXT NOT NULL,
    object TEXT NOT NULL,
    confidence REAL NOT NULL DEFAULT 0.8,
    created_at TEXT DEFAULT (datetime('now'))
);
CREATE INDEX IF NOT EXISTS idx_triple_session_agent ON memory_triples(session_id, agent_id);
CREATE INDEX IF NOT EXISTS idx_triple_subject ON memory_triples(session_id, subject);
CREATE INDEX IF NOT EXISTS idx_triple_object ON memory_triples(session_id, object);
-- Composite index for recursive CTE joins in get_relational_context()
CREATE INDEX IF NOT EXISTS idx_triple_search ON memory_triples(session_id, agent_id, subject, object);

-- ============================================================
-- kg_snapshots: 知識圖譜時序快照（#4）
-- ============================================================
CREATE TABLE IF NOT EXISTS kg_snapshots (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id TEXT NOT NULL,
    round_number INTEGER NOT NULL DEFAULT 0,
    snapshot_json TEXT NOT NULL DEFAULT '{}',
    node_count INTEGER NOT NULL DEFAULT 0,
    edge_count INTEGER NOT NULL DEFAULT 0,
    created_at TEXT DEFAULT (datetime('now'))
);
CREATE INDEX IF NOT EXISTS idx_snapshot_session_round ON kg_snapshots(session_id, round_number);

-- ============================================================
-- kg_edges dynamic columns migration（#4）
-- ============================================================
-- Note: ALTER TABLE ADD COLUMN IF NOT EXISTS not supported in older SQLite
-- Use CREATE TABLE IF NOT EXISTS pattern to avoid errors on re-run

-- ============================================================
-- agent_relationships: 社會網絡（#7）
-- ============================================================
CREATE TABLE IF NOT EXISTS agent_relationships (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id TEXT NOT NULL,
    agent_a_id INTEGER NOT NULL,
    agent_b_id INTEGER NOT NULL,
    relationship_type TEXT NOT NULL,
    influence_weight REAL NOT NULL DEFAULT 1.0,
    trust_score REAL DEFAULT 0.0,
    created_at TEXT DEFAULT (datetime('now'))
);
CREATE INDEX IF NOT EXISTS idx_rel_session ON agent_relationships(session_id);
CREATE UNIQUE INDEX IF NOT EXISTS idx_rel_pair ON agent_relationships(session_id, agent_a_id, agent_b_id);

-- ============================================================
-- market_data: 市場數據（#6）
-- ============================================================
CREATE TABLE IF NOT EXISTS market_data (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    date TEXT NOT NULL,
    asset_type TEXT NOT NULL,
    ticker TEXT NOT NULL,
    open REAL,
    close REAL,
    high REAL,
    low REAL,
    volume REAL,
    source TEXT NOT NULL DEFAULT 'hkex',
    created_at TEXT DEFAULT (datetime('now'))
);
CREATE INDEX IF NOT EXISTS idx_market_ticker_date ON market_data(ticker, date);

-- ============================================================
-- scenario_branches: 多情景對比（#8）
-- ============================================================
CREATE TABLE IF NOT EXISTS scenario_branches (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    parent_session_id TEXT NOT NULL REFERENCES simulation_sessions(id),
    branch_session_id TEXT NOT NULL REFERENCES simulation_sessions(id),
    scenario_variant TEXT NOT NULL,
    label TEXT NOT NULL,
    fork_round INTEGER,
    created_at TEXT DEFAULT (datetime('now'))
);
CREATE INDEX IF NOT EXISTS idx_branch_parent ON scenario_branches(parent_session_id);

-- ============================================================
-- social_sentiment: LIHKG 社交情感指標
-- ============================================================
CREATE TABLE IF NOT EXISTS social_sentiment (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    period TEXT NOT NULL,
    category TEXT NOT NULL,
    positive_ratio REAL NOT NULL DEFAULT 0.0,
    negative_ratio REAL NOT NULL DEFAULT 0.0,
    neutral_ratio REAL NOT NULL DEFAULT 0.0,
    thread_count INTEGER NOT NULL DEFAULT 0,
    total_engagement INTEGER NOT NULL DEFAULT 0,
    source TEXT NOT NULL DEFAULT 'lihkg',
    created_at TEXT DEFAULT (datetime('now'))
);
CREATE INDEX IF NOT EXISTS idx_sentiment_period ON social_sentiment(period);
CREATE INDEX IF NOT EXISTS idx_sentiment_category ON social_sentiment(category);

-- ============================================================
-- agent_decisions: Agent 人生決策（Phase 1）
-- ============================================================
CREATE TABLE IF NOT EXISTS agent_decisions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id TEXT NOT NULL,
    agent_id INTEGER NOT NULL,
    round_number INTEGER NOT NULL,
    decision_type TEXT NOT NULL,
    action TEXT NOT NULL,
    reasoning TEXT,
    confidence REAL NOT NULL DEFAULT 0.5,
    created_at TEXT DEFAULT (datetime('now'))
);
CREATE INDEX IF NOT EXISTS idx_decision_session ON agent_decisions(session_id, round_number);

-- ============================================================
-- ensemble_results: Monte Carlo 結果（Phase 2B）
-- ============================================================
CREATE TABLE IF NOT EXISTS ensemble_results (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id TEXT NOT NULL,
    n_trials INTEGER NOT NULL,
    metric_name TEXT NOT NULL,
    p10 REAL, p25 REAL, p50 REAL, p75 REAL, p90 REAL,
    created_at TEXT DEFAULT (datetime('now'))
);
CREATE INDEX IF NOT EXISTS idx_ensemble_session ON ensemble_results(session_id);

-- ============================================================
-- company_profiles: 企業 Agent（Phase 5）
-- ============================================================
CREATE TABLE IF NOT EXISTS company_profiles (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id TEXT NOT NULL,
    company_name TEXT NOT NULL,
    company_type TEXT NOT NULL,
    industry_sector TEXT NOT NULL,
    company_size TEXT NOT NULL,
    district TEXT,
    supply_chain_position TEXT,
    annual_revenue_hkd INTEGER,
    employee_count INTEGER,
    china_exposure REAL DEFAULT 0.5,
    export_ratio REAL DEFAULT 0.3,
    created_at TEXT DEFAULT (datetime('now'))
);
CREATE INDEX IF NOT EXISTS idx_company_session ON company_profiles(session_id);

-- ============================================================
-- company_decisions: 企業決策（Phase 5）
-- ============================================================
CREATE TABLE IF NOT EXISTS company_decisions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id TEXT NOT NULL,
    company_id INTEGER NOT NULL,
    round_number INTEGER NOT NULL,
    decision_type TEXT NOT NULL,
    action TEXT NOT NULL,
    reasoning TEXT,
    confidence REAL NOT NULL DEFAULT 0.5,
    impact_employees INTEGER DEFAULT 0,
    impact_revenue_pct REAL DEFAULT 0.0,
    created_at TEXT DEFAULT (datetime('now'))
);
CREATE INDEX IF NOT EXISTS idx_company_decision_session ON company_decisions(session_id, round_number);

-- ============================================================
-- media_agents: 媒體 Agent（Phase 6）
-- ============================================================
CREATE TABLE IF NOT EXISTS media_agents (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id TEXT NOT NULL,
    media_name TEXT NOT NULL,
    political_lean REAL NOT NULL DEFAULT 0.5,
    influence_radius INTEGER DEFAULT 50,
    credibility REAL DEFAULT 0.7,
    created_at TEXT DEFAULT (datetime('now'))
);
CREATE INDEX IF NOT EXISTS idx_media_session ON media_agents(session_id);

-- ============================================================
-- Phase 6: Political Modeling column migration note
-- ============================================================
-- political_stance is added to agent_profiles at runtime via ALTER TABLE
-- (see PoliticalModel.ensure_column() in services/political_model.py).
-- Column: political_stance REAL DEFAULT 0.5
--   0.0 = 建制派 (pro-establishment)
--   0.5 = 中間派 (centrist)
--   1.0 = 民主派 (pro-democracy)

-- ============================================================
-- Phase 1B: Temporal Async Activation column migration note
-- ============================================================
-- Two columns added to agent_profiles at runtime via ALTER TABLE
-- (see store_activity_profiles() in services/simulation_manager.py).
-- Columns:
--   chronotype TEXT  — 'morning_lark' | 'standard' | 'evening_owl' | 'night_shift'
--   activity_vector TEXT  — JSON array of 24 floats (hour 0–23 activity probabilities)
-- Primary storage: data/sessions/{session_id}/activity_profiles.json
-- Used by SimulationRunner._is_agent_active() to gate action logging per round.

-- ============================================================
-- data_provenance: 數據來源追蹤
-- ============================================================
CREATE TABLE IF NOT EXISTS data_provenance (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    category TEXT NOT NULL,
    metric TEXT NOT NULL,
    source_type TEXT NOT NULL,
    source_url TEXT,
    fetch_timestamp TEXT NOT NULL,
    record_count INTEGER NOT NULL,
    coverage_start TEXT,
    coverage_end TEXT,
    notes TEXT,
    created_at TEXT DEFAULT (datetime('now'))
);
CREATE INDEX IF NOT EXISTS idx_provenance_cat ON data_provenance(category, metric);

-- ============================================================
-- news_headlines: 新聞標題（情緒分析用）
-- ============================================================
CREATE TABLE IF NOT EXISTS news_headlines (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    title TEXT NOT NULL,
    published TEXT,
    source TEXT NOT NULL,
    url TEXT,
    category TEXT DEFAULT 'general',
    sentiment TEXT,
    created_at TEXT DEFAULT (datetime('now'))
);
CREATE INDEX IF NOT EXISTS idx_headlines_source ON news_headlines(source);

-- ============================================================
-- agent_consumption: B2C 消費追蹤（Phase C）
-- ============================================================
CREATE TABLE IF NOT EXISTS agent_consumption (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id TEXT NOT NULL,
    agent_id INTEGER NOT NULL,
    round_number INTEGER NOT NULL,
    category TEXT NOT NULL,
    amount_pct REAL NOT NULL,
    created_at TEXT DEFAULT (datetime('now'))
);
CREATE INDEX IF NOT EXISTS idx_consumption_session
    ON agent_consumption(session_id, round_number);

-- ============================================================
-- echo_chamber_snapshots: 同溫層快照
-- ============================================================
CREATE TABLE IF NOT EXISTS echo_chamber_snapshots (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id TEXT NOT NULL,
    round_number INTEGER NOT NULL,
    num_clusters INTEGER NOT NULL DEFAULT 0,
    modularity REAL NOT NULL DEFAULT 0.0,
    cluster_data_json TEXT NOT NULL DEFAULT '[]',
    agent_to_cluster_json TEXT NOT NULL DEFAULT '{}',
    created_at TEXT DEFAULT (datetime('now'))
);
CREATE INDEX IF NOT EXISTS idx_echo_session_round ON echo_chamber_snapshots(session_id, round_number);

-- ============================================================
-- community_summaries: GraphRAG 社群摘要（Phase 18）
-- Created at runtime via CREATE TABLE IF NOT EXISTS in graph_rag.py
-- ============================================================
-- CREATE TABLE IF NOT EXISTS community_summaries (
--     id INTEGER PRIMARY KEY AUTOINCREMENT,
--     session_id TEXT NOT NULL,
--     round_number INTEGER NOT NULL,
--     cluster_id INTEGER NOT NULL,
--     core_narrative TEXT NOT NULL,
--     shared_anxieties TEXT NOT NULL DEFAULT '',
--     main_opposition TEXT NOT NULL DEFAULT '',
--     member_count INTEGER NOT NULL DEFAULT 0,
--     avg_trust REAL NOT NULL DEFAULT 0.0,
--     created_at TEXT DEFAULT (datetime('now')),
--     UNIQUE(session_id, round_number, cluster_id)
-- );
-- LanceDB: cs_{session_id[:12]} table stores community summary embeddings (384-dim)

-- ============================================================
-- users: 用戶帳號（Phase 4.8 Authentication）
-- ============================================================
CREATE TABLE IF NOT EXISTS users (
    id TEXT PRIMARY KEY,
    email TEXT UNIQUE NOT NULL,
    password_hash TEXT NOT NULL,
    display_name TEXT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
CREATE INDEX IF NOT EXISTS idx_users_email ON users(email);

-- ============================================================
-- calibration_results: 參數校準結果（Phase B）
-- ============================================================
CREATE TABLE IF NOT EXISTS calibration_results (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    label TEXT NOT NULL,
    params_json TEXT NOT NULL,
    rmse REAL,
    data_period TEXT,
    created_at TEXT DEFAULT (datetime('now'))
);

-- ============================================================
-- workspaces: 協作工作空間（Phase 4.6）
-- ============================================================
CREATE TABLE IF NOT EXISTS workspaces (
    id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    description TEXT,
    owner_id TEXT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- ============================================================
-- workspace_members: 工作空間成員
-- ============================================================
CREATE TABLE IF NOT EXISTS workspace_members (
    workspace_id TEXT NOT NULL,
    user_id TEXT NOT NULL,
    role TEXT DEFAULT 'viewer',
    joined_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (workspace_id, user_id)
);

-- ============================================================
-- workspace_sessions: 工作空間內嘅模擬 session
-- ============================================================
CREATE TABLE IF NOT EXISTS workspace_sessions (
    workspace_id TEXT NOT NULL,
    session_id TEXT NOT NULL,
    added_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (workspace_id, session_id)
);

-- ============================================================
-- prediction_comments: 預測評論系統
-- ============================================================
CREATE TABLE IF NOT EXISTS prediction_comments (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id TEXT NOT NULL,
    user_id TEXT,
    content TEXT NOT NULL,
    quote_text TEXT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
CREATE INDEX IF NOT EXISTS idx_comments_session ON prediction_comments(session_id);

-- ============================================================
-- custom_domain_packs: User-generated or LLM-generated domain packs
-- ============================================================
CREATE TABLE IF NOT EXISTS custom_domain_packs (
    id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    description TEXT DEFAULT '',
    regions TEXT NOT NULL,
    occupations TEXT NOT NULL,
    income_brackets TEXT NOT NULL,
    shocks TEXT NOT NULL,
    metrics TEXT NOT NULL,
    persona_template TEXT NOT NULL,
    sentiment_keywords TEXT NOT NULL,
    locale TEXT DEFAULT 'en-US',
    source TEXT DEFAULT 'user_edited',
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
CREATE INDEX IF NOT EXISTS idx_custom_packs_locale ON custom_domain_packs(locale);

-- ============================================================
-- network_events: Phase 1C Dynamic Network Evolution
-- ============================================================
CREATE TABLE IF NOT EXISTS network_events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id TEXT NOT NULL,
    round_number INTEGER NOT NULL,
    event_type TEXT NOT NULL,
    agent_a_username TEXT NOT NULL DEFAULT '',
    agent_b_username TEXT NOT NULL DEFAULT '',
    trust_delta REAL NOT NULL DEFAULT 0.0,
    details_json TEXT NOT NULL DEFAULT '{}',
    created_at TEXT DEFAULT (datetime('now'))
);
CREATE INDEX IF NOT EXISTS idx_nev_session ON network_events(session_id);
CREATE INDEX IF NOT EXISTS idx_nev_round ON network_events(session_id, round_number);
CREATE INDEX IF NOT EXISTS idx_nev_type ON network_events(session_id, event_type);

-- ============================================================
-- agent_feeds: Phase 2 Recommendation Engine — per-agent ranked feeds
-- ============================================================
CREATE TABLE IF NOT EXISTS agent_feeds (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id TEXT NOT NULL,
    agent_id INTEGER NOT NULL,
    round_number INTEGER NOT NULL,
    post_id TEXT NOT NULL,
    rank INTEGER NOT NULL,
    score REAL NOT NULL,
    created_at TEXT DEFAULT (datetime('now'))
);
CREATE INDEX IF NOT EXISTS idx_af_session_round ON agent_feeds(session_id, round_number);
CREATE INDEX IF NOT EXISTS idx_af_agent ON agent_feeds(session_id, agent_id, round_number);

-- ============================================================
-- filter_bubble_snapshots: Phase 2 per-round filter bubble report
-- ============================================================
CREATE TABLE IF NOT EXISTS filter_bubble_snapshots (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id TEXT NOT NULL,
    round_number INTEGER NOT NULL,
    avg_bubble_score REAL NOT NULL DEFAULT 0.0,
    median_bubble_score REAL NOT NULL DEFAULT 0.0,
    pct_in_bubble REAL NOT NULL DEFAULT 0.0,
    algorithm TEXT NOT NULL DEFAULT 'engagement_first',
    gini_coefficient REAL NOT NULL DEFAULT 0.0,
    created_at TEXT DEFAULT (datetime('now')),
    UNIQUE(session_id, round_number)
);

-- ============================================================
-- virality_scores: Phase 2 post virality metrics
-- ============================================================
CREATE TABLE IF NOT EXISTS virality_scores (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id TEXT NOT NULL,
    post_id TEXT NOT NULL,
    cascade_depth INTEGER NOT NULL DEFAULT 0,
    cascade_breadth INTEGER NOT NULL DEFAULT 0,
    velocity REAL NOT NULL DEFAULT 0.0,
    reproduction_number REAL NOT NULL DEFAULT 0.0,
    cross_cluster_reach REAL NOT NULL DEFAULT 0.0,
    virality_index REAL NOT NULL DEFAULT 0.0,
    created_at TEXT DEFAULT (datetime('now')),
    UNIQUE(session_id, post_id)
);
CREATE INDEX IF NOT EXISTS idx_vs_session ON virality_scores(session_id);

-- ============================================================
-- Phase 3: Emotional States (VAD model per agent per round)
-- ============================================================
CREATE TABLE IF NOT EXISTS emotional_states (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id TEXT NOT NULL,
    agent_id INTEGER NOT NULL,
    round_number INTEGER NOT NULL,
    valence REAL NOT NULL DEFAULT 0.0,
    arousal REAL NOT NULL DEFAULT 0.3,
    dominance REAL NOT NULL DEFAULT 0.4,
    created_at TEXT DEFAULT (datetime('now')),
    UNIQUE(session_id, agent_id, round_number)
);
CREATE INDEX IF NOT EXISTS idx_es_session ON emotional_states(session_id, round_number);

-- ============================================================
-- Phase 3: Belief States (per agent per topic per round)
-- ============================================================
CREATE TABLE IF NOT EXISTS belief_states (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id TEXT NOT NULL,
    agent_id INTEGER NOT NULL,
    topic TEXT NOT NULL,
    stance REAL NOT NULL DEFAULT 0.0,
    confidence REAL NOT NULL DEFAULT 0.5,
    evidence_count INTEGER NOT NULL DEFAULT 0,
    round_number INTEGER NOT NULL,
    created_at TEXT DEFAULT (datetime('now')),
    UNIQUE(session_id, agent_id, topic, round_number)
);
CREATE INDEX IF NOT EXISTS idx_bs_session ON belief_states(session_id, round_number);
CREATE INDEX IF NOT EXISTS idx_bs_agent ON belief_states(session_id, agent_id);

-- ============================================================
-- Phase 3: Cognitive Dissonance (per agent per round)
-- ============================================================
CREATE TABLE IF NOT EXISTS cognitive_dissonance (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id TEXT NOT NULL,
    agent_id INTEGER NOT NULL,
    round_number INTEGER NOT NULL,
    dissonance_score REAL NOT NULL DEFAULT 0.0,
    conflicting_pairs_json TEXT NOT NULL DEFAULT '[]',
    action_belief_gap REAL NOT NULL DEFAULT 0.0,
    resolution_strategy TEXT NOT NULL DEFAULT 'none',
    created_at TEXT DEFAULT (datetime('now')),
    UNIQUE(session_id, agent_id, round_number)
);
CREATE INDEX IF NOT EXISTS idx_cd_session ON cognitive_dissonance(session_id, round_number);

-- ============================================================
-- Phase 4A: Scale Benchmarks (profiling run results)
-- ============================================================
CREATE TABLE IF NOT EXISTS scale_benchmarks (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    target_name TEXT NOT NULL,
    agent_count INTEGER NOT NULL,
    rounds_completed INTEGER NOT NULL,
    total_duration_s REAL NOT NULL,
    avg_round_duration_s REAL NOT NULL,
    peak_memory_mb REAL NOT NULL DEFAULT 0,
    db_queries_total INTEGER NOT NULL DEFAULT 0,
    db_avg_query_ms REAL NOT NULL DEFAULT 0.0,
    llm_calls_total INTEGER NOT NULL DEFAULT 0,
    llm_avg_latency_ms REAL NOT NULL DEFAULT 0.0,
    hook_durations_json TEXT NOT NULL DEFAULT '{}',
    bottleneck_hook TEXT NOT NULL DEFAULT '',
    throughput REAL NOT NULL DEFAULT 0.0,
    passed INTEGER NOT NULL DEFAULT 0,
    created_at TEXT DEFAULT (datetime('now'))
);
CREATE INDEX IF NOT EXISTS idx_sb_target ON scale_benchmarks(target_name);
CREATE INDEX IF NOT EXISTS idx_sb_created ON scale_benchmarks(created_at);

-- ============================================================
-- Universal Cognitive Simulation Engine (kg_driven mode only)
-- ============================================================

CREATE TABLE IF NOT EXISTS cognitive_fingerprints (
    agent_id               TEXT PRIMARY KEY,
    simulation_id          TEXT NOT NULL,
    values_json            TEXT NOT NULL,
    info_diet_json         TEXT NOT NULL,
    group_memberships_json TEXT NOT NULL,
    susceptibility_json    TEXT NOT NULL,
    confirmation_bias      REAL NOT NULL DEFAULT 0.5,
    conformity             REAL NOT NULL DEFAULT 0.5,
    created_at             TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS world_events (
    id                 TEXT PRIMARY KEY,
    simulation_id      TEXT NOT NULL,
    round_number       INTEGER NOT NULL,
    content            TEXT NOT NULL,
    event_type         TEXT NOT NULL,
    reach_json         TEXT NOT NULL,
    impact_vector_json TEXT NOT NULL,
    credibility        REAL NOT NULL DEFAULT 1.0,
    created_at         TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS faction_snapshots_v2 (
    id                      TEXT PRIMARY KEY,
    simulation_id           TEXT NOT NULL,
    round_number            INTEGER NOT NULL,
    factions_json           TEXT NOT NULL,
    bridge_agents_json      TEXT NOT NULL,
    modularity_score        REAL NOT NULL,
    inter_faction_hostility REAL NOT NULL,
    created_at              TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS tipping_points (
    id                     TEXT PRIMARY KEY,
    simulation_id          TEXT NOT NULL,
    round_number           INTEGER NOT NULL,
    trigger_event_id       TEXT,
    kl_divergence          REAL NOT NULL,
    change_direction       TEXT NOT NULL,
    affected_factions_json TEXT NOT NULL,
    created_at             TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS narrative_traces (
    id                   TEXT PRIMARY KEY,
    simulation_id        TEXT NOT NULL,
    agent_id             TEXT NOT NULL,
    round_number         INTEGER NOT NULL,
    received_events_json TEXT NOT NULL,
    belief_delta_json    TEXT NOT NULL,
    decision             TEXT,
    llm_reasoning        TEXT,
    faction_changed      INTEGER NOT NULL DEFAULT 0,
    created_at           TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS multi_run_results (
    id                         TEXT PRIMARY KEY,
    simulation_id              TEXT NOT NULL,
    trial_count                INTEGER NOT NULL,
    outcome_distribution_json  TEXT NOT NULL,
    most_common_path_json      TEXT NOT NULL,
    confidence_intervals_json  TEXT NOT NULL,
    avg_tipping_point_round    REAL,
    faction_stability_score    REAL,
    created_at                 TEXT NOT NULL DEFAULT (datetime('now'))
);

-- ============================================================
-- seed_world_context: 群體記憶 / 宏觀背景（Step 1 注入）
-- ============================================================
CREATE TABLE IF NOT EXISTS seed_world_context (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    graph_id     TEXT    NOT NULL,
    session_id   TEXT,
    context_type TEXT    NOT NULL,
    title        TEXT    NOT NULL,
    content      TEXT    NOT NULL,
    severity     REAL    NOT NULL DEFAULT 0.7,
    phase        TEXT    NOT NULL DEFAULT 'crisis',
    lance_row_id TEXT,
    created_at   TEXT    DEFAULT (datetime('now')),
    UNIQUE(graph_id, title) ON CONFLICT IGNORE
);
CREATE INDEX IF NOT EXISTS idx_swc_graph   ON seed_world_context(graph_id);
CREATE INDEX IF NOT EXISTS idx_swc_session ON seed_world_context(session_id);

-- ============================================================
-- seed_persona_templates: 個體人設模板（Step 1 注入，Step 2 消費）
-- ============================================================
CREATE TABLE IF NOT EXISTS seed_persona_templates (
    id                     INTEGER PRIMARY KEY AUTOINCREMENT,
    graph_id               TEXT    NOT NULL,
    session_id             TEXT,
    agent_type_key         TEXT    NOT NULL,
    display_name           TEXT    NOT NULL,
    age_min                INTEGER,
    age_max                INTEGER,
    region_hint            TEXT    NOT NULL DEFAULT 'any',
    population_ratio       REAL    NOT NULL DEFAULT 0.25,
    initial_memories_json  TEXT    NOT NULL,
    personality_hints_json TEXT    NOT NULL,
    created_at             TEXT    DEFAULT (datetime('now')),
    UNIQUE(graph_id, agent_type_key) ON CONFLICT IGNORE
);
CREATE INDEX IF NOT EXISTS idx_spt_graph   ON seed_persona_templates(graph_id);
CREATE INDEX IF NOT EXISTS idx_spt_session ON seed_persona_templates(session_id);

-- ---------------------------------------------------------------------------
-- relationship_states: Multi-dimensional per-agent-pair relationship state
-- Added in: relationship simulation capability (Phase 1)
-- Directional: (session_id, agent_a_id, agent_b_id, round_number) is the unique key.
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS relationship_states (
    id                  INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id          TEXT    NOT NULL,
    agent_a_id          TEXT    NOT NULL,
    agent_b_id          TEXT    NOT NULL,
    round_number        INTEGER NOT NULL DEFAULT 0,
    intimacy            REAL    NOT NULL DEFAULT 0.1,
    passion             REAL    NOT NULL DEFAULT 0.1,
    commitment          REAL    NOT NULL DEFAULT 0.1,
    satisfaction        REAL    NOT NULL DEFAULT 0.1,
    alternatives        REAL    NOT NULL DEFAULT 0.3,
    investment          REAL    NOT NULL DEFAULT 0.05,
    trust               REAL    NOT NULL DEFAULT 0.0,
    interaction_count   INTEGER NOT NULL DEFAULT 0,
    rounds_since_change INTEGER NOT NULL DEFAULT 0,
    created_at          TEXT    DEFAULT (datetime('now')),
    updated_at          TEXT    DEFAULT (datetime('now'))
);
CREATE UNIQUE INDEX IF NOT EXISTS idx_rs_pair
    ON relationship_states(session_id, agent_a_id, agent_b_id, round_number);
CREATE INDEX IF NOT EXISTS idx_rs_session
    ON relationship_states(session_id, round_number);

-- ---------------------------------------------------------------------------
-- attachment_styles: Per-agent attachment style (inferred from Big Five)
-- Added in: relationship simulation capability (Phase 1)
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS attachment_styles (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id  TEXT    NOT NULL,
    agent_id    TEXT    NOT NULL,
    style       TEXT    NOT NULL DEFAULT 'secure',
    anxiety     REAL    NOT NULL DEFAULT 0.2,
    avoidance   REAL    NOT NULL DEFAULT 0.2,
    created_at  TEXT    DEFAULT (datetime('now')),
    UNIQUE(session_id, agent_id) ON CONFLICT REPLACE
);
CREATE INDEX IF NOT EXISTS idx_as_session ON attachment_styles(session_id);
