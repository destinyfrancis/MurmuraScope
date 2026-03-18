# backend/tests/test_implicit_stakeholder_prompts.py
from backend.prompts.implicit_stakeholder_prompts import (
    IMPLICIT_STAKEHOLDER_SYSTEM,
    IMPLICIT_STAKEHOLDER_USER,
)

def test_system_prompt_has_no_hk_references():
    for term in ["Hong Kong", "香港", "HKMA", "HKD"]:
        assert term not in IMPLICIT_STAKEHOLDER_SYSTEM

def test_user_prompt_has_required_placeholders():
    assert "{seed_text}" in IMPLICIT_STAKEHOLDER_USER
    assert "{existing_nodes_json}" in IMPLICIT_STAKEHOLDER_USER
    assert "{node_count}" in IMPLICIT_STAKEHOLDER_USER

def test_system_prompt_references_output_schema():
    assert "implied_actors" in IMPLICIT_STAKEHOLDER_SYSTEM
    assert "relevance_reason" in IMPLICIT_STAKEHOLDER_SYSTEM
