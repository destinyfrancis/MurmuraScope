"""Tests for domain pack models (Task 8)."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from backend.app.models.domain import APISourceConfig, DraftDomainPack, FieldMapping

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _valid_pack(**overrides) -> DraftDomainPack:
    """Return a minimal valid DraftDomainPack, with optional field overrides."""
    defaults = dict(
        id="test_pack",
        name="Test Pack",
        regions=["Region A", "Region B", "Region C"],
        occupations=["Occ1", "Occ2", "Occ3", "Occ4", "Occ5"],
        income_brackets=["low", "mid", "high"],
        shocks=["shock1", "shock2", "shock3", "shock4"],
        metrics=["metric1", "metric2", "metric3"],
        persona_template="You are a {occupation} in {region}.",
        sentiment_keywords=["good"] * 20,
        locale="en-US",
    )
    defaults.update(overrides)
    return DraftDomainPack(**defaults)


# ---------------------------------------------------------------------------
# DraftDomainPack — happy path
# ---------------------------------------------------------------------------


def test_draft_domain_pack_valid():
    pack = _valid_pack()
    assert pack.id == "test_pack"
    assert len(pack.regions) == 3


def test_draft_domain_pack_default_source():
    pack = _valid_pack()
    assert pack.source == "generated"


def test_draft_domain_pack_user_edited_source():
    pack = _valid_pack(source="user_edited")
    assert pack.source == "user_edited"


def test_draft_domain_pack_builtin_source():
    pack = _valid_pack(source="builtin")
    assert pack.source == "builtin"


def test_draft_domain_pack_default_locale():
    pack = _valid_pack()
    assert pack.locale == "en-US"


def test_draft_domain_pack_custom_locale():
    pack = _valid_pack(locale="zh-HK")
    assert pack.locale == "zh-HK"


def test_draft_domain_pack_description_optional():
    pack = _valid_pack()
    assert pack.description == ""


def test_draft_domain_pack_description_set():
    pack = _valid_pack(description="A custom domain")
    assert pack.description == "A custom domain"


def test_draft_domain_pack_more_regions():
    pack = _valid_pack(regions=["A", "B", "C", "D", "E"])
    assert len(pack.regions) == 5


def test_draft_domain_pack_more_shocks():
    pack = _valid_pack(shocks=["s1", "s2", "s3", "s4", "s5", "s6"])
    assert len(pack.shocks) == 6


def test_draft_domain_pack_more_keywords():
    pack = _valid_pack(sentiment_keywords=["word"] * 50)
    assert len(pack.sentiment_keywords) == 50


# ---------------------------------------------------------------------------
# DraftDomainPack — frozen (immutability)
# ---------------------------------------------------------------------------


def test_draft_domain_pack_frozen():
    pack = _valid_pack()
    with pytest.raises(Exception):
        pack.name = "changed"  # type: ignore[misc]


def test_draft_domain_pack_frozen_list_field():
    pack = _valid_pack()
    with pytest.raises(Exception):
        pack.regions = ["X", "Y", "Z"]  # type: ignore[misc]


# ---------------------------------------------------------------------------
# DraftDomainPack — validation errors
# ---------------------------------------------------------------------------


def test_regions_too_few():
    with pytest.raises(ValidationError, match="regions must have at least 3"):
        _valid_pack(regions=["A", "B"])


def test_regions_empty():
    with pytest.raises(ValidationError, match="regions must have at least 3"):
        _valid_pack(regions=[])


def test_shocks_too_few():
    with pytest.raises(ValidationError, match="shocks must have at least 4"):
        _valid_pack(shocks=["s1", "s2", "s3"])


def test_metrics_too_few():
    with pytest.raises(ValidationError, match="metrics must have at least 3"):
        _valid_pack(metrics=["m1", "m2"])


def test_sentiment_keywords_too_few():
    with pytest.raises(ValidationError, match="sentiment_keywords must have at least 20"):
        _valid_pack(sentiment_keywords=["good"] * 19)


def test_invalid_source_literal():
    with pytest.raises(ValidationError):
        _valid_pack(source="unknown_source")  # type: ignore[arg-type]


# ---------------------------------------------------------------------------
# APISourceConfig
# ---------------------------------------------------------------------------


def test_api_source_config_defaults():
    cfg = APISourceConfig(url="https://api.example.com/data")
    assert cfg.auth_type == "none"
    assert cfg.auth_value is None
    assert cfg.json_path == "$"
    assert cfg.polling_hours == 24


def test_api_source_config_bearer():
    cfg = APISourceConfig(
        url="https://api.example.com/data",
        auth_type="bearer",
        auth_value="secret123",
        json_path="$.data.records",
        polling_hours=12,
    )
    assert cfg.url == "https://api.example.com/data"
    assert cfg.polling_hours == 12
    assert cfg.auth_type == "bearer"
    assert cfg.auth_value == "secret123"
    assert cfg.json_path == "$.data.records"


def test_api_source_config_api_key_header():
    cfg = APISourceConfig(
        url="https://api.example.com/data",
        auth_type="api_key_header",
        auth_value="my_key",
    )
    assert cfg.auth_type == "api_key_header"


def test_api_source_config_api_key_query():
    cfg = APISourceConfig(
        url="https://api.example.com/data",
        auth_type="api_key_query",
        auth_value="my_key",
    )
    assert cfg.auth_type == "api_key_query"


def test_api_source_config_frozen():
    cfg = APISourceConfig(url="https://api.example.com/data")
    with pytest.raises(Exception):
        cfg.url = "https://other.example.com"  # type: ignore[misc]


def test_api_source_config_invalid_auth_type():
    with pytest.raises(ValidationError):
        APISourceConfig(
            url="https://api.example.com",
            auth_type="oauth2",  # type: ignore[arg-type]
        )


# ---------------------------------------------------------------------------
# FieldMapping
# ---------------------------------------------------------------------------


def test_field_mapping_defaults():
    fm = FieldMapping(source_field="price", target_metric="index")
    assert fm.transform == "raw"
    assert fm.confidence == 0.0


def test_field_mapping_yoy_pct():
    fm = FieldMapping(
        source_field="avg_price",
        target_metric="property_index",
        transform="yoy_pct",
        confidence=0.85,
    )
    assert fm.transform == "yoy_pct"
    assert fm.confidence == 0.85


def test_field_mapping_all_transforms():
    for t in ("raw", "yoy_pct", "mom_pct", "cumsum", "normalize"):
        fm = FieldMapping(source_field="f", target_metric="m", transform=t)
        assert fm.transform == t


def test_field_mapping_frozen():
    fm = FieldMapping(source_field="f", target_metric="m")
    with pytest.raises(Exception):
        fm.source_field = "other"  # type: ignore[misc]


def test_field_mapping_invalid_transform():
    with pytest.raises(ValidationError):
        FieldMapping(
            source_field="f",
            target_metric="m",
            transform="log_transform",  # type: ignore[arg-type]
        )
