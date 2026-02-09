"""Tests for the data source registry."""

import pytest

from src.data.data_source_registry import (
    CATEGORIES,
    DATA_SOURCE_MAP,
    DATA_SOURCES,
    DEFAULT_SOURCES,
    PROVIDER_HEALTH_URLS,
    DataSourceDef,
    get_sources_by_category,
    get_unique_providers,
)


class TestDataSourceRegistry:
    """Test the static data source catalog."""

    def test_all_sources_have_unique_ids(self):
        ids = [ds.id for ds in DATA_SOURCES]
        assert len(ids) == len(set(ids)), "Duplicate data source IDs found"

    def test_all_sources_have_required_fields(self):
        for ds in DATA_SOURCES:
            assert ds.id, f"Source missing id"
            assert ds.name, f"Source {ds.id} missing name"
            assert ds.description, f"Source {ds.id} missing description"
            assert ds.category in CATEGORIES, f"Source {ds.id} has invalid category: {ds.category}"
            assert ds.provider, f"Source {ds.id} missing provider"
            assert isinstance(ds.free, bool)
            assert isinstance(ds.default, bool)

    def test_all_sources_are_free(self):
        for ds in DATA_SOURCES:
            assert ds.free is True, f"Source {ds.id} is not free"

    def test_map_matches_list(self):
        assert len(DATA_SOURCE_MAP) == len(DATA_SOURCES)
        for ds in DATA_SOURCES:
            assert ds.id in DATA_SOURCE_MAP
            assert DATA_SOURCE_MAP[ds.id] is ds

    def test_default_sources_exist(self):
        for src_id in DEFAULT_SOURCES:
            assert src_id in DATA_SOURCE_MAP, f"Default source {src_id} not in registry"

    def test_default_sources_match_default_flag(self):
        expected = sorted([ds.id for ds in DATA_SOURCES if ds.default])
        actual = sorted(DEFAULT_SOURCES)
        assert actual == expected

    def test_minimum_source_count(self):
        assert len(DATA_SOURCES) >= 20, f"Expected at least 20 sources, got {len(DATA_SOURCES)}"

    def test_minimum_default_count(self):
        assert len(DEFAULT_SOURCES) >= 5, f"Expected at least 5 defaults, got {len(DEFAULT_SOURCES)}"

    def test_all_categories_represented(self):
        categories_in_use = {ds.category for ds in DATA_SOURCES}
        for cat in CATEGORIES:
            assert cat in categories_in_use, f"Category {cat} has no sources"

    def test_get_sources_by_category(self):
        futures = get_sources_by_category("futures")
        assert len(futures) >= 3
        assert all(ds.category == "futures" for ds in futures)

        empty = get_sources_by_category("nonexistent")
        assert len(empty) == 0

    def test_get_unique_providers(self):
        providers = get_unique_providers()
        assert "Binance" in providers
        assert "Calculated" not in providers  # Excluded

    def test_provider_health_urls_cover_external_providers(self):
        external_providers = {ds.provider for ds in DATA_SOURCES if ds.provider != "Calculated"}
        for provider in external_providers:
            assert provider in PROVIDER_HEALTH_URLS, f"Missing health URL for provider: {provider}"

    def test_to_dict(self):
        ds = DATA_SOURCES[0]
        d = ds.to_dict()
        assert d["id"] == ds.id
        assert d["name"] == ds.name
        assert d["category"] == ds.category
        assert d["provider"] == ds.provider
        assert d["free"] is True

    def test_dataclass_is_frozen(self):
        ds = DATA_SOURCES[0]
        with pytest.raises(AttributeError):
            ds.id = "modified"  # type: ignore
