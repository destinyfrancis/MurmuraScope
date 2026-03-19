"""Tests for store_universal_agent_profiles."""
import pytest
from unittest.mock import AsyncMock, patch
from backend.app.models.universal_agent_profile import UniversalAgentProfile


def _make_profile(
    id_: str = "iran_leader",
    name: str = "Khamenei",
    entity_type: str = "state_leader",
) -> UniversalAgentProfile:
    return UniversalAgentProfile(
        id=id_,
        name=name,
        role="Supreme Leader",
        entity_type=entity_type,
        persona="Hardline conservative theocratic leader",
        goals=("Preserve regime", "Nuclear deterrence"),
        capabilities=("Military command", "Religious authority"),
        stance_axes=(("hawkishness", 0.9), ("diplomacy", 0.2)),
        relationships=(("israel", "adversary"), ("russia", "ally")),
        kg_node_id=f"abc12345_{id_}",
        openness=0.2,
        conscientiousness=0.8,
        extraversion=0.3,
        agreeableness=0.1,
        neuroticism=0.4,
    )


@pytest.mark.asyncio
async def test_store_universal_agent_profiles_basic():
    from backend.app.services.simulation_manager import store_universal_agent_profiles

    profiles = [_make_profile(), _make_profile("us_president", "Biden", "state_leader")]

    mock_db = AsyncMock()
    mock_db.__aenter__ = AsyncMock(return_value=mock_db)
    mock_db.__aexit__ = AsyncMock(return_value=False)

    with patch("backend.app.services.simulation_manager.get_db", return_value=mock_db):
        await store_universal_agent_profiles("test-session-123", profiles)

    mock_db.executemany.assert_called_once()
    call_args = mock_db.executemany.call_args
    sql = call_args[0][0]
    rows = call_args[0][1]
    assert "INSERT INTO agent_profiles" in sql
    assert len(rows) == 2
    assert rows[0][0] == "test-session-123"


@pytest.mark.asyncio
async def test_store_universal_agent_profiles_field_mapping():
    """Verify universal fields map correctly to HK-schema columns."""
    from backend.app.services.simulation_manager import store_universal_agent_profiles

    profile = _make_profile()
    profiles = [profile]

    mock_db = AsyncMock()
    mock_db.__aenter__ = AsyncMock(return_value=mock_db)
    mock_db.__aexit__ = AsyncMock(return_value=False)

    with patch("backend.app.services.simulation_manager.get_db", return_value=mock_db):
        await store_universal_agent_profiles("sess-1", profiles)

    row = mock_db.executemany.call_args[0][1][0]
    # session_id, agent_type, age, sex, district, occupation, ...
    assert row[0] == "sess-1"             # session_id
    assert row[1] == "state_leader"       # agent_type = entity_type
    assert row[2] == 0                    # age
    assert row[3] == "N/A"               # sex
    assert row[4] == "state_leader"       # district = entity_type
    assert row[5] == "Supreme Leader"     # occupation = role
    assert row[6] == "N/A"               # income_bracket
    assert row[10] == 0.2                # openness
    assert row[14] == 0.4                # neuroticism
    assert row[15] == 0                  # monthly_income
    assert row[16] == 0                  # savings
    assert row[17] == profile.persona    # oasis_persona


@pytest.mark.asyncio
async def test_store_universal_agent_profiles_empty_list():
    """Empty profile list should still call executemany with empty rows."""
    from backend.app.services.simulation_manager import store_universal_agent_profiles

    mock_db = AsyncMock()
    mock_db.__aenter__ = AsyncMock(return_value=mock_db)
    mock_db.__aexit__ = AsyncMock(return_value=False)

    with patch("backend.app.services.simulation_manager.get_db", return_value=mock_db):
        await store_universal_agent_profiles("sess-empty", [])

    rows = mock_db.executemany.call_args[0][1]
    assert len(rows) == 0
    mock_db.commit.assert_called_once()


@pytest.mark.asyncio
async def test_store_universal_agent_profiles_oasis_username():
    """oasis_username should come from to_oasis_row(), not raw id."""
    from backend.app.services.simulation_manager import store_universal_agent_profiles

    profile = _make_profile()
    expected_username = profile.to_oasis_row()["username"]

    mock_db = AsyncMock()
    mock_db.__aenter__ = AsyncMock(return_value=mock_db)
    mock_db.__aexit__ = AsyncMock(return_value=False)

    with patch("backend.app.services.simulation_manager.get_db", return_value=mock_db):
        await store_universal_agent_profiles("sess-u", [profile])

    row = mock_db.executemany.call_args[0][1][0]
    assert row[18] == expected_username  # oasis_username
