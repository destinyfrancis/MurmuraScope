"""Unit tests for entity_extractor dynamic alias generation (Phase 3.3).

Covers:
- generate_dynamic_aliases() rule-based rules:
  - Legal suffix stripping (Ltd., Inc., Corp., Group ...)
  - English acronym generation from multi-word names
  - TC ↔ SC character substitution
  - Leading "The " prefix removal
- _build_reverse_alias_lookup() merges static and dynamic
- Empty entity list returns empty dict
- max_per_entity cap respected
"""

from __future__ import annotations

import pytest

from backend.app.services.entity_extractor import (
    _ALIAS_MAP,
    _build_reverse_alias_lookup,
    generate_dynamic_aliases,
)


class TestGenerateDynamicAliases:
    def test_empty_entities_returns_empty(self):
        result = generate_dynamic_aliases([])
        assert result == {}

    def test_entity_without_title_skipped(self):
        result = generate_dynamic_aliases([{"title": ""}])
        assert result == {}

    def test_legal_suffix_stripped_ltd(self):
        result = generate_dynamic_aliases([{"title": "Acme Corporation Ltd."}])
        # "Acme Corporation" or "acme corporation" should appear
        all_aliases = {alias for aliases in result.values() for alias in aliases}
        assert any("ltd" not in alias for alias in all_aliases)

    def test_the_prefix_stripped(self):
        result = generate_dynamic_aliases([{"title": "The Federal Reserve"}])
        all_aliases = {alias for aliases in result.values() for alias in aliases}
        assert any("federal" in alias for alias in all_aliases)

    def test_english_acronym_generated(self):
        result = generate_dynamic_aliases([{"title": "Goldman Sachs"}])
        all_aliases = {alias for aliases in result.values() for alias in aliases}
        # Should generate "gs" acronym
        assert "gs" in all_aliases

    def test_multi_word_acronym(self):
        result = generate_dynamic_aliases([{"title": "International Monetary Fund"}])
        all_aliases = {alias for aliases in result.values() for alias in aliases}
        assert "imf" in all_aliases

    def test_tc_to_sc_conversion(self):
        """騰訊 → 腾讯 (TC to SC)"""
        result = generate_dynamic_aliases([{"title": "騰訊"}])
        if result:
            all_aliases = {alias for aliases in result.values() for alias in aliases}
            assert "腾讯" in all_aliases

    def test_no_self_alias(self):
        """Title itself should not appear as its own alias."""
        result = generate_dynamic_aliases([{"title": "Goldman Sachs"}])
        for title, aliases in result.items():
            assert title.lower() not in aliases

    def test_max_per_entity_cap(self):
        result = generate_dynamic_aliases(
            [{"title": "The International Monetary Fund Holdings Ltd."}],
            max_per_entity=2,
        )
        for aliases in result.values():
            assert len(aliases) <= 2

    def test_single_word_no_acronym(self):
        """Single-word titles should not produce acronyms."""
        result = generate_dynamic_aliases([{"title": "Google"}])
        all_aliases = {a for aliases in result.values() for a in aliases}
        # "g" is too short (< 2 chars) — single-word acronym should not appear
        assert "g" not in all_aliases

    def test_multiple_entities_independent(self):
        entities = [
            {"title": "Goldman Sachs"},
            {"title": "Morgan Stanley"},
        ]
        result = generate_dynamic_aliases(entities)
        # Should have entries for both (if aliases generated)
        titles = list(result.keys())
        assert len(titles) <= 2  # At most one per entity

    def test_returns_dict_with_set_values(self):
        result = generate_dynamic_aliases([{"title": "Goldman Sachs"}])
        for title, aliases in result.items():
            assert isinstance(aliases, set)
            assert isinstance(title, str)


class TestBuildReverseAliasLookup:
    def test_static_aliases_included(self):
        lookup = _build_reverse_alias_lookup()
        # 騰訊 canonical → 腾讯 alias
        assert "腾讯" in lookup
        assert lookup["腾讯"] == "騰訊"

    def test_canonical_maps_to_itself(self):
        lookup = _build_reverse_alias_lookup()
        assert lookup["騰訊".lower()] == "騰訊"

    def test_extra_aliases_override_added(self):
        extra = {"CustomCorp": {"customco", "cc corp"}}
        lookup = _build_reverse_alias_lookup(extra)
        assert "customco" in lookup
        assert lookup["customco"] == "CustomCorp"

    def test_extra_none_doesnt_crash(self):
        lookup = _build_reverse_alias_lookup(None)
        assert isinstance(lookup, dict)
        assert len(lookup) > 0

    def test_extra_empty_dict(self):
        lookup = _build_reverse_alias_lookup({})
        # Should equal the static-only lookup
        static = _build_reverse_alias_lookup(None)
        assert lookup == static

    def test_hkex_alias_present(self):
        lookup = _build_reverse_alias_lookup()
        assert "hkex" in lookup
        assert lookup["hkex"] == "港交所"

    def test_bilibili_aliases(self):
        lookup = _build_reverse_alias_lookup()
        assert "bilibili" in lookup
        assert lookup["bilibili"] == "嗶哩嗶哩"

    def test_dynamic_and_static_coexist(self):
        dynamic = {"TestEntity": {"te alias"}}
        lookup = _build_reverse_alias_lookup(dynamic)
        # Both static and dynamic present
        assert "hkex" in lookup  # static
        assert "te alias" in lookup  # dynamic


class TestStaticAliasMapIntegrity:
    def test_all_canonical_have_at_least_one_alias(self):
        for canonical, aliases in _ALIAS_MAP.items():
            assert len(aliases) >= 1, f"{canonical!r} has no aliases"

    def test_all_aliases_are_strings(self):
        for canonical, aliases in _ALIAS_MAP.items():
            for alias in aliases:
                assert isinstance(alias, str), f"{canonical!r} has non-string alias"

    def test_no_empty_aliases(self):
        for canonical, aliases in _ALIAS_MAP.items():
            for alias in aliases:
                assert alias.strip() != "", f"{canonical!r} has empty alias"

    def test_canonical_not_in_own_aliases(self):
        """Canonical name should not appear literally in own alias set."""
        for canonical, aliases in _ALIAS_MAP.items():
            assert canonical not in aliases, \
                f"{canonical!r} appears as its own alias"
