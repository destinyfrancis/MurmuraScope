"""Tests for echo chamber detection and social contagion.

Covers:
- Task 1: Dynamic community detection (Louvain) + filter bubble dampening
- Task 2: Cognitive-macro bridge (social contagion context injection)
"""

from __future__ import annotations

from pathlib import Path

import aiosqlite
import pytest

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

SCHEMA_PATH = Path(__file__).parent.parent / "database" / "schema.sql"


@pytest.fixture
async def db_path(tmp_path):
    """Create a temporary DB with full schema."""
    path = tmp_path / "test.db"
    async with aiosqlite.connect(str(path)) as db:
        schema = SCHEMA_PATH.read_text()
        await db.executescript(schema)
        # Ensure memory_triples table exists
        await db.execute("""
            CREATE TABLE IF NOT EXISTS memory_triples (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                memory_id INTEGER,
                session_id TEXT NOT NULL,
                agent_id INTEGER NOT NULL,
                round_number INTEGER NOT NULL,
                subject TEXT NOT NULL,
                predicate TEXT NOT NULL,
                object TEXT NOT NULL,
                confidence REAL DEFAULT 0.85,
                created_at TEXT DEFAULT (datetime('now'))
            )
        """)
        await db.commit()
    return path


@pytest.fixture
def mock_db(db_path, monkeypatch):
    """Patch get_db to use the temp database."""
    import contextlib

    @contextlib.asynccontextmanager
    async def _get_db():
        db = await aiosqlite.connect(str(db_path))
        db.row_factory = aiosqlite.Row
        try:
            yield db
        finally:
            await db.close()

    monkeypatch.setattr("backend.app.services.social_network.get_db", _get_db)
    monkeypatch.setattr("backend.app.services.decision_deliberator.get_db", _get_db)
    monkeypatch.setattr("backend.app.services.trust_dynamics.get_db", _get_db)
    return db_path


async def _seed_agents_and_relationships(db_path: Path, session_id: str = "test-session"):
    """Seed 6 agents in 2 clusters with trust scores."""
    async with aiosqlite.connect(str(db_path)) as db:
        # Create 6 agents: 3 in cluster A (Central), 3 in cluster B (Tsuen Wan)
        # Each tuple includes oasis_persona (NOT NULL) and oasis_username
        agents = [
            (
                session_id,
                "citizen",
                30,
                "M",
                "Central",
                "finance",
                "high",
                "university",
                "single",
                "private",
                0.7,
                0.5,
                0.8,
                0.5,
                0.3,
                50000,
                200000,
                "金融從業員A1",
                "user_a1",
            ),
            (
                session_id,
                "citizen",
                35,
                "F",
                "Central",
                "finance",
                "high",
                "university",
                "married",
                "private",
                0.6,
                0.6,
                0.7,
                0.6,
                0.4,
                45000,
                150000,
                "金融從業員A2",
                "user_a2",
            ),
            (
                session_id,
                "citizen",
                28,
                "M",
                "Central",
                "finance",
                "high",
                "university",
                "single",
                "rental",
                0.5,
                0.5,
                0.6,
                0.5,
                0.5,
                35000,
                80000,
                "金融從業員A3",
                "user_a3",
            ),
            (
                session_id,
                "citizen",
                45,
                "F",
                "Tsuen Wan",
                "education",
                "middle",
                "university",
                "married",
                "public",
                0.4,
                0.7,
                0.3,
                0.7,
                0.6,
                25000,
                100000,
                "教育工作者B1",
                "user_b1",
            ),
            (
                session_id,
                "citizen",
                50,
                "M",
                "Tsuen Wan",
                "education",
                "middle",
                "secondary",
                "married",
                "public",
                0.3,
                0.6,
                0.4,
                0.8,
                0.7,
                22000,
                60000,
                "教育工作者B2",
                "user_b2",
            ),
            (
                session_id,
                "citizen",
                40,
                "F",
                "Tsuen Wan",
                "education",
                "middle",
                "university",
                "married",
                "public",
                0.5,
                0.5,
                0.5,
                0.6,
                0.5,
                28000,
                90000,
                "教育工作者B3",
                "user_b3",
            ),
        ]
        for a in agents:
            await db.execute(
                """INSERT INTO agent_profiles
                   (session_id, agent_type, age, sex, district, occupation,
                    income_bracket, education_level, marital_status, housing_type,
                    openness, conscientiousness, extraversion, agreeableness,
                    neuroticism, monthly_income, savings,
                    oasis_persona, oasis_username)
                   VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                a,
            )
        await db.commit()

        # Get inserted IDs
        cursor = await db.execute(
            "SELECT id, district FROM agent_profiles WHERE session_id = ? ORDER BY id",
            (session_id,),
        )
        rows = await cursor.fetchall()
        ids = [r[0] for r in rows]

        # Create intra-cluster relationships with HIGH trust
        # Cluster A: ids[0], ids[1], ids[2] (Central finance)
        for i in range(3):
            for j in range(i + 1, 3):
                await db.execute(
                    """INSERT INTO agent_relationships
                       (session_id, agent_a_id, agent_b_id, relationship_type,
                        influence_weight, trust_score)
                       VALUES (?, ?, ?, 'colleague', 0.8, 0.7)""",
                    (session_id, ids[i], ids[j]),
                )
                await db.execute(
                    """INSERT INTO agent_relationships
                       (session_id, agent_a_id, agent_b_id, relationship_type,
                        influence_weight, trust_score)
                       VALUES (?, ?, ?, 'colleague', 0.8, 0.7)""",
                    (session_id, ids[j], ids[i]),
                )

        # Cluster B: ids[3], ids[4], ids[5] (Tsuen Wan education)
        for i in range(3, 6):
            for j in range(i + 1, 6):
                await db.execute(
                    """INSERT INTO agent_relationships
                       (session_id, agent_a_id, agent_b_id, relationship_type,
                        influence_weight, trust_score)
                       VALUES (?, ?, ?, 'colleague', 0.7, 0.6)""",
                    (session_id, ids[i], ids[j]),
                )
                await db.execute(
                    """INSERT INTO agent_relationships
                       (session_id, agent_a_id, agent_b_id, relationship_type,
                        influence_weight, trust_score)
                       VALUES (?, ?, ?, 'colleague', 0.7, 0.6)""",
                    (session_id, ids[j], ids[i]),
                )

        # Cross-cluster with NEGATIVE trust (distrust)
        await db.execute(
            """INSERT INTO agent_relationships
               (session_id, agent_a_id, agent_b_id, relationship_type,
                influence_weight, trust_score)
               VALUES (?, ?, ?, 'interaction', 0.3, -0.5)""",
            (session_id, ids[0], ids[3]),
        )
        await db.execute(
            """INSERT INTO agent_relationships
               (session_id, agent_a_id, agent_b_id, relationship_type,
                influence_weight, trust_score)
               VALUES (?, ?, ?, 'interaction', 0.3, -0.5)""",
            (session_id, ids[3], ids[0]),
        )

        await db.commit()
        return ids


# ===========================================================================
# Task 1: Echo Chamber Detection
# ===========================================================================


class TestEchoChamberDetection:
    """Test detect_echo_chambers() in SocialNetworkBuilder."""

    @pytest.mark.asyncio
    async def test_detects_two_clusters(self, mock_db):
        """Two distinct trust clusters should be detected."""
        from backend.app.services.social_network import SocialNetworkBuilder

        ids = await _seed_agents_and_relationships(mock_db, "test-echo")
        builder = SocialNetworkBuilder()
        result = await builder.detect_echo_chambers("test-echo")

        assert result.num_clusters >= 2
        assert len(result.chambers) >= 2
        assert result.modularity > 0.0

    @pytest.mark.asyncio
    async def test_agent_to_cluster_mapping(self, mock_db):
        """Every agent should have a cluster assignment."""
        from backend.app.services.social_network import SocialNetworkBuilder

        ids = await _seed_agents_and_relationships(mock_db, "test-map")
        builder = SocialNetworkBuilder()
        result = await builder.detect_echo_chambers("test-map")

        for aid in ids:
            assert aid in result.agent_to_cluster

    @pytest.mark.asyncio
    async def test_intra_cluster_agents_grouped(self, mock_db):
        """Agents with high mutual trust should be in the same cluster."""
        from backend.app.services.social_network import SocialNetworkBuilder

        ids = await _seed_agents_and_relationships(mock_db, "test-group")
        builder = SocialNetworkBuilder()
        result = await builder.detect_echo_chambers("test-group")

        # Central finance agents (ids[0:3]) should share a cluster
        cluster_a = result.agent_to_cluster[ids[0]]
        assert result.agent_to_cluster[ids[1]] == cluster_a
        assert result.agent_to_cluster[ids[2]] == cluster_a

        # Tsuen Wan education agents (ids[3:6]) should share a cluster
        cluster_b = result.agent_to_cluster[ids[3]]
        assert result.agent_to_cluster[ids[4]] == cluster_b
        assert result.agent_to_cluster[ids[5]] == cluster_b

    @pytest.mark.asyncio
    async def test_different_clusters_for_distrusted_groups(self, mock_db):
        """Agents with negative cross-trust should be in different clusters."""
        from backend.app.services.social_network import SocialNetworkBuilder

        ids = await _seed_agents_and_relationships(mock_db, "test-split")
        builder = SocialNetworkBuilder()
        result = await builder.detect_echo_chambers("test-split")

        cluster_a = result.agent_to_cluster[ids[0]]
        cluster_b = result.agent_to_cluster[ids[3]]
        assert cluster_a != cluster_b

    @pytest.mark.asyncio
    async def test_echo_chamber_frozen(self, mock_db):
        """EchoChamber and EchoChamberResult should be frozen."""
        from backend.app.services.social_network import (
            SocialNetworkBuilder,
        )

        ids = await _seed_agents_and_relationships(mock_db, "test-frozen")
        builder = SocialNetworkBuilder()
        result = await builder.detect_echo_chambers("test-frozen")

        with pytest.raises(AttributeError):
            result.modularity = 999.0  # type: ignore[misc]

        if result.chambers:
            with pytest.raises(AttributeError):
                result.chambers[0].cluster_id = 999  # type: ignore[misc]

    @pytest.mark.asyncio
    async def test_empty_session(self, mock_db):
        """No agents should return empty result."""
        from backend.app.services.social_network import SocialNetworkBuilder

        builder = SocialNetworkBuilder()
        result = await builder.detect_echo_chambers("nonexistent-session")

        assert result.num_clusters == 0
        assert result.chambers == ()
        assert result.agent_to_cluster == {}

    @pytest.mark.asyncio
    async def test_modularity_positive(self, mock_db):
        """Modularity should be positive when clear community structure exists."""
        from backend.app.services.social_network import SocialNetworkBuilder

        ids = await _seed_agents_and_relationships(mock_db, "test-mod")
        builder = SocialNetworkBuilder()
        result = await builder.detect_echo_chambers("test-mod")

        assert result.modularity > 0.0

    @pytest.mark.asyncio
    async def test_avg_trust_computed(self, mock_db):
        """Each chamber should have computed avg_trust."""
        from backend.app.services.social_network import SocialNetworkBuilder

        ids = await _seed_agents_and_relationships(mock_db, "test-trust")
        builder = SocialNetworkBuilder()
        result = await builder.detect_echo_chambers("test-trust")

        for chamber in result.chambers:
            if chamber.size > 1:
                # Intra-cluster trust is positive
                assert chamber.avg_trust > 0.0


class TestFilterBubbleDampening:
    """Test cross-cluster memory dampening."""

    @pytest.mark.asyncio
    async def test_cross_cluster_dampening_applied(self, mock_db):
        """Memories from distrusted cross-cluster agents should be dampened."""
        from backend.app.services.social_network import SocialNetworkBuilder

        session_id = "test-dampen"
        ids = await _seed_agents_and_relationships(mock_db, session_id)

        # Seed memories and actions for this round
        async with aiosqlite.connect(str(mock_db)) as db:
            # Agent ids[3] (Tsuen Wan) posts in round 3
            await db.execute(
                """INSERT INTO simulation_actions
                   (session_id, round_number, agent_id, oasis_username,
                    action_type, platform, content)
                   VALUES (?, 3, ?, 'user_b1', 'post', 'facebook', '今日天氣好好')""",
                (session_id, ids[3]),
            )
            # Agent ids[0] (Central) has a memory in round 3
            await db.execute(
                """INSERT INTO agent_memories
                   (session_id, agent_id, round_number, memory_text,
                    salience_score, memory_type)
                   VALUES (?, ?, 3, '聽到有人話今日天氣好好', 0.8, 'observation')""",
                (session_id, ids[0]),
            )
            await db.commit()

        builder = SocialNetworkBuilder()
        result = await builder.detect_echo_chambers(session_id)

        # Apply dampening
        dampened = await builder.apply_echo_chamber_dampening(session_id, 3, result)

        # Check that the memory salience was reduced
        async with aiosqlite.connect(str(mock_db)) as db:
            cursor = await db.execute(
                "SELECT salience_score FROM agent_memories WHERE session_id = ? AND agent_id = ?",
                (session_id, ids[0]),
            )
            row = await cursor.fetchone()

        if dampened > 0:
            assert row[0] < 0.8  # Dampened from original 0.8

    @pytest.mark.asyncio
    async def test_same_cluster_no_dampening(self, mock_db):
        """Memories from same-cluster agents should not be dampened."""
        from backend.app.services.social_network import SocialNetworkBuilder

        session_id = "test-no-dampen"
        ids = await _seed_agents_and_relationships(mock_db, session_id)

        # Agent ids[1] (Central, same cluster as ids[0]) posts
        async with aiosqlite.connect(str(mock_db)) as db:
            await db.execute(
                """INSERT INTO simulation_actions
                   (session_id, round_number, agent_id, oasis_username,
                    action_type, platform, content)
                   VALUES (?, 3, ?, 'user_a2', 'post', 'facebook', '股市升咗')""",
                (session_id, ids[1]),
            )
            await db.execute(
                """INSERT INTO agent_memories
                   (session_id, agent_id, round_number, memory_text,
                    salience_score, memory_type)
                   VALUES (?, ?, 3, '同事話股市升咗', 0.9, 'observation')""",
                (session_id, ids[0]),
            )
            await db.commit()

        builder = SocialNetworkBuilder()
        result = await builder.detect_echo_chambers(session_id)
        dampened = await builder.apply_echo_chamber_dampening(session_id, 3, result)

        # Same cluster → no dampening
        async with aiosqlite.connect(str(mock_db)) as db:
            cursor = await db.execute(
                "SELECT salience_score FROM agent_memories WHERE session_id = ? AND agent_id = ?",
                (session_id, ids[0]),
            )
            row = await cursor.fetchone()
            assert row[0] == pytest.approx(0.9, abs=0.01)


# ===========================================================================
# Task 2: Cognitive-Macro Bridge (Social Contagion)
# ===========================================================================


class TestSocialContagion:
    """Test social contagion context for decision deliberation."""

    @pytest.mark.asyncio
    async def test_contagion_from_trusted_peer_decisions(self, mock_db):
        """Should detect distress from trusted peers' emigration decisions."""
        from backend.app.models.decision import DecisionType
        from backend.app.services.decision_deliberator import DecisionDeliberator

        session_id = "test-contagion"
        ids = await _seed_agents_and_relationships(mock_db, session_id)

        # Seed emigration decisions from trusted peers (ids[1], ids[2])
        async with aiosqlite.connect(str(mock_db)) as db:
            await db.execute("""
                CREATE TABLE IF NOT EXISTS agent_decisions (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    session_id TEXT NOT NULL,
                    agent_id INTEGER NOT NULL,
                    round_number INTEGER NOT NULL,
                    decision_type TEXT NOT NULL,
                    action TEXT NOT NULL,
                    reasoning TEXT,
                    confidence REAL DEFAULT 0.5,
                    created_at TEXT DEFAULT (datetime('now'))
                )
            """)
            for peer_id in [ids[1], ids[2]]:
                await db.execute(
                    """INSERT INTO agent_decisions
                       (session_id, agent_id, round_number, decision_type,
                        action, reasoning, confidence)
                       VALUES (?, ?, 5, 'emigrate', 'emigrate',
                               '政治環境差，決定走', 0.85)""",
                    (session_id, peer_id),
                )
            await db.commit()

        deliberator = DecisionDeliberator()
        ctx = await deliberator.query_social_contagion(session_id, ids[0], DecisionType.EMIGRATE)

        assert len(ctx.distress_signals) >= 2
        assert all(s.trust_score >= 0.3 for s in ctx.distress_signals)

    @pytest.mark.asyncio
    async def test_contagion_from_memory_triples(self, mock_db):
        """Should detect distress from trusted peers' memory triples."""
        from backend.app.models.decision import DecisionType
        from backend.app.services.decision_deliberator import DecisionDeliberator

        session_id = "test-triples"
        ids = await _seed_agents_and_relationships(mock_db, session_id)

        # Seed distress triples from trusted peers
        async with aiosqlite.connect(str(mock_db)) as db:
            for i, peer_id in enumerate([ids[1], ids[2]]):
                await db.execute(
                    """INSERT INTO memory_triples
                       (memory_id, session_id, agent_id, round_number,
                        subject, predicate, object, confidence)
                       VALUES (?, ?, ?, 3, '我', 'worries_about', '移民', 0.9)""",
                    (i + 100, session_id, peer_id),
                )
                await db.execute(
                    """INSERT INTO memory_triples
                       (memory_id, session_id, agent_id, round_number,
                        subject, predicate, object, confidence)
                       VALUES (?, ?, ?, 3, '經濟', 'decreases', '信心', 0.85)""",
                    (i + 200, session_id, peer_id),
                )
            await db.commit()

        deliberator = DecisionDeliberator()
        ctx = await deliberator.query_social_contagion(session_id, ids[0], DecisionType.EMIGRATE)

        assert len(ctx.distress_signals) >= 2

    @pytest.mark.asyncio
    async def test_contagion_threshold_3_peers(self, mock_db):
        """Contagion should only activate when ≥3 trusted peers show distress."""
        from backend.app.models.decision import DecisionType
        from backend.app.services.decision_deliberator import DecisionDeliberator

        session_id = "test-threshold"
        ids = await _seed_agents_and_relationships(mock_db, session_id)

        # Only 1 peer with distress triple → contagion should NOT activate
        async with aiosqlite.connect(str(mock_db)) as db:
            await db.execute(
                """INSERT INTO memory_triples
                   (memory_id, session_id, agent_id, round_number,
                    subject, predicate, object, confidence)
                   VALUES (1, ?, ?, 3, '我', 'worries_about', '樓價', 0.9)""",
                (session_id, ids[1]),
            )
            await db.commit()

        deliberator = DecisionDeliberator()
        ctx = await deliberator.query_social_contagion(session_id, ids[0], DecisionType.BUY_PROPERTY)

        assert not ctx.contagion_active
        assert len(ctx.distress_signals) <= 2

    @pytest.mark.asyncio
    async def test_contagion_context_frozen(self, mock_db):
        """SocialContagionContext should be frozen."""
        from backend.app.services.decision_deliberator import SocialContagionContext

        ctx = SocialContagionContext(
            agent_id=1,
            distress_signals=(),
            distress_ratio=0.0,
            contagion_active=False,
        )
        with pytest.raises(AttributeError):
            ctx.contagion_active = True  # type: ignore[misc]

    @pytest.mark.asyncio
    async def test_peer_distress_signal_frozen(self, mock_db):
        """PeerDistressSignal should be frozen."""
        from backend.app.services.decision_deliberator import PeerDistressSignal

        sig = PeerDistressSignal(
            peer_agent_id=1,
            peer_username="user_a",
            signal_type="triple",
            detail="worries_about: 移民",
            trust_score=0.7,
        )
        with pytest.raises(AttributeError):
            sig.trust_score = 0.0  # type: ignore[misc]

    @pytest.mark.asyncio
    async def test_contagion_prompt_section(self, mock_db):
        """Active contagion should produce a non-empty prompt section."""
        from backend.app.services.decision_deliberator import (
            PeerDistressSignal,
            SocialContagionContext,
        )

        signals = tuple(
            PeerDistressSignal(
                peer_agent_id=i,
                peer_username=f"user_{i}",
                signal_type="decision",
                detail="決定 emigrate (走咗)",
                trust_score=0.7,
            )
            for i in range(3)
        )

        ctx = SocialContagionContext(
            agent_id=1,
            distress_signals=signals,
            distress_ratio=0.75,
            contagion_active=True,
        )
        section = ctx.to_prompt_section()

        assert "社交傳染警報" in section
        assert "SOCIAL CONTAGION" in section
        assert "user_0" in section
        assert "群體恐慌" in section

    @pytest.mark.asyncio
    async def test_inactive_contagion_empty_prompt(self, mock_db):
        """Inactive contagion should produce empty prompt section."""
        from backend.app.services.decision_deliberator import SocialContagionContext

        ctx = SocialContagionContext(
            agent_id=1,
            distress_signals=(),
            distress_ratio=0.0,
            contagion_active=False,
        )
        assert ctx.to_prompt_section() == ""

    @pytest.mark.asyncio
    async def test_no_trusted_peers_no_contagion(self, mock_db):
        """Agent with no trusted peers should have no contagion."""
        from backend.app.models.decision import DecisionType
        from backend.app.services.decision_deliberator import DecisionDeliberator

        session_id = "test-no-peers"
        # Seed agents but NO relationships
        async with aiosqlite.connect(str(mock_db)) as db:
            await db.execute(
                """INSERT INTO agent_profiles
                   (session_id, agent_type, age, sex, district, occupation,
                    income_bracket, education_level, marital_status, housing_type,
                    openness, conscientiousness, extraversion, agreeableness,
                    neuroticism, monthly_income, savings,
                    oasis_persona, oasis_username)
                   VALUES ('test-no-peers', 'citizen', 30, 'M', 'Central', 'finance',
                           'high', 'university', 'single', 'private',
                           0.5, 0.5, 0.5, 0.5, 0.5, 30000, 100000,
                           '孤獨金融人', 'lonely_user')""",
            )
            await db.commit()
            cursor = await db.execute("SELECT id FROM agent_profiles WHERE session_id = 'test-no-peers'")
            row = await cursor.fetchone()
            agent_id = row[0]

        deliberator = DecisionDeliberator()
        ctx = await deliberator.query_social_contagion(session_id, agent_id, DecisionType.EMIGRATE)

        assert not ctx.contagion_active
        assert len(ctx.distress_signals) == 0
        assert ctx.distress_ratio == 0.0


def _make_test_macro():
    """Build a minimal MacroState for testing."""
    from backend.app.services.macro_state import (
        BASELINE_AVG_SQFT_PRICE,
        BASELINE_STAMP_DUTY,
        MacroState,
    )

    return MacroState(
        hibor_1m=0.04,
        prime_rate=0.055,
        unemployment_rate=0.032,
        median_monthly_income=20_800,
        ccl_index=150.0,
        avg_sqft_price=dict(BASELINE_AVG_SQFT_PRICE),
        mortgage_cap=0.70,
        stamp_duty_rates=dict(BASELINE_STAMP_DUTY),
        gdp_growth=0.025,
        cpi_yoy=0.019,
        hsi_level=20_060.0,
        consumer_confidence=70.0,
        net_migration=2_000,
        birth_rate=5.3,
        policy_flags={},
    )


class TestDeliberationPromptWithContagion:
    """Test that contagion context is properly injected into prompts."""

    def test_prompt_without_contagion(self):
        """Without contagion, prompt should not contain contagion section."""
        from backend.app.models.decision import DecisionType
        from backend.app.services.agent_factory import AgentProfile
        from backend.prompts.decision_prompts import build_deliberation_prompt

        profile = AgentProfile(
            id=1,
            agent_type="citizen",
            age=30,
            sex="M",
            district="Central",
            occupation="finance",
            income_bracket="high",
            education_level="university",
            marital_status="single",
            housing_type="private",
            openness=0.5,
            conscientiousness=0.5,
            extraversion=0.5,
            agreeableness=0.5,
            neuroticism=0.5,
            monthly_income=30000,
            savings=100000,
        )
        macro = _make_test_macro()

        messages = build_deliberation_prompt(
            [profile],
            macro,
            DecisionType.EMIGRATE,
            contagion_context=None,
        )

        user_msg = messages[1]["content"]
        assert "社交傳染警報" not in user_msg

    def test_prompt_with_contagion(self):
        """With contagion, prompt should contain the contagion section."""
        from backend.app.models.decision import DecisionType
        from backend.app.services.agent_factory import AgentProfile
        from backend.prompts.decision_prompts import build_deliberation_prompt

        profile = AgentProfile(
            id=1,
            agent_type="citizen",
            age=30,
            sex="M",
            district="Central",
            occupation="finance",
            income_bracket="high",
            education_level="university",
            marital_status="single",
            housing_type="private",
            openness=0.5,
            conscientiousness=0.5,
            extraversion=0.5,
            agreeableness=0.5,
            neuroticism=0.5,
            monthly_income=30000,
            savings=100000,
        )
        macro = _make_test_macro()

        contagion = (
            "--- agent_id=1 社交傳染 ---\n【社交傳染警報 SOCIAL CONTAGION】\n你信任嘅朋友/同事中，3 個人正經歷困擾"
        )

        messages = build_deliberation_prompt(
            [profile],
            macro,
            DecisionType.EMIGRATE,
            contagion_context=contagion,
        )

        user_msg = messages[1]["content"]
        assert "社交傳染" in user_msg
        assert "SOCIAL CONTAGION" in user_msg

    def test_system_prompt_mentions_contagion(self):
        """System prompt should mention social contagion effect."""
        from backend.prompts.decision_prompts import SYSTEM_PROMPT

        assert "社交傳染" in SYSTEM_PROMPT
        assert "群體恐慌" in SYSTEM_PROMPT
