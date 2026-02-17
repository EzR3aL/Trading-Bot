"""Tests for the data source registry module."""

import pytest

from src.data.data_source_registry import (
    DATA_SOURCES,
    DATA_SOURCE_MAP,
    DEFAULT_SOURCES,
    CATEGORIES,
    PROVIDER_HEALTH_URLS,
    DataSourceDef,
    get_sources_by_category,
    get_unique_providers,
)


class TestDataSourceDef:
    """Tests for the DataSourceDef dataclass."""

    def test_create_data_source(self):
        ds = DataSourceDef(
            id="test", name="Test", description="A test source",
            category="spot", provider="TestProvider", free=True, default=False,
        )
        assert ds.id == "test"
        assert ds.free is True
        assert ds.default is False

    def test_to_dict(self):
        ds = DataSourceDef(
            id="test", name="Test", description="desc",
            category="spot", provider="P", free=True, default=True,
        )
        d = ds.to_dict()
        assert isinstance(d, dict)
        assert d["id"] == "test"
        assert d["free"] is True

    def test_frozen_immutable(self):
        ds = DataSourceDef(
            id="test", name="Test", description="desc",
            category="spot", provider="P", free=True, default=True,
        )
        with pytest.raises(AttributeError):
            ds.id = "changed"


class TestDataSources:
    """Tests for the DATA_SOURCES constant."""

    def test_data_sources_not_empty(self):
        assert len(DATA_SOURCES) > 0

    def test_all_have_required_fields(self):
        for ds in DATA_SOURCES:
            assert ds.id, f"Missing id for {ds}"
            assert ds.name, f"Missing name for {ds.id}"
            assert ds.category in CATEGORIES, f"Invalid category for {ds.id}: {ds.category}"

    def test_unique_ids(self):
        ids = [ds.id for ds in DATA_SOURCES]
        assert len(ids) == len(set(ids)), "Duplicate data source IDs found"

    def test_all_are_free(self):
        for ds in DATA_SOURCES:
            assert ds.free is True, f"{ds.id} is not free"


class TestDataSourceMap:
    """Tests for DATA_SOURCE_MAP lookup."""

    def test_map_contains_all_sources(self):
        assert len(DATA_SOURCE_MAP) == len(DATA_SOURCES)

    def test_lookup_by_id(self):
        assert DATA_SOURCE_MAP["fear_greed"].name == "Fear & Greed Index"
        assert DATA_SOURCE_MAP["funding_rate"].category == "futures"

    def test_missing_key_raises(self):
        with pytest.raises(KeyError):
            _ = DATA_SOURCE_MAP["nonexistent"]


class TestDefaultSources:
    """Tests for DEFAULT_SOURCES."""

    def test_defaults_not_empty(self):
        assert len(DEFAULT_SOURCES) > 0

    def test_defaults_are_valid_ids(self):
        for src_id in DEFAULT_SOURCES:
            assert src_id in DATA_SOURCE_MAP

    def test_defaults_match_default_flag(self):
        expected = [ds.id for ds in DATA_SOURCES if ds.default]
        assert DEFAULT_SOURCES == expected


class TestGetSourcesByCategory:
    """Tests for get_sources_by_category."""

    def test_sentiment_category(self):
        sources = get_sources_by_category("sentiment")
        assert all(s.category == "sentiment" for s in sources)
        assert len(sources) >= 1

    def test_futures_category(self):
        sources = get_sources_by_category("futures")
        assert all(s.category == "futures" for s in sources)
        assert len(sources) >= 1

    def test_empty_category(self):
        sources = get_sources_by_category("nonexistent")
        assert sources == []


class TestGetUniqueProviders:
    """Tests for get_unique_providers."""

    def test_returns_sorted_list(self):
        providers = get_unique_providers()
        assert providers == sorted(providers)

    def test_excludes_calculated(self):
        providers = get_unique_providers()
        assert "Calculated" not in providers

    def test_includes_known_providers(self):
        providers = get_unique_providers()
        assert "Binance" in providers
        assert "Alternative.me" in providers


class TestProviderHealthUrls:
    """Tests for PROVIDER_HEALTH_URLS."""

    def test_all_external_providers_have_urls(self):
        providers = get_unique_providers()
        for provider in providers:
            assert provider in PROVIDER_HEALTH_URLS, f"Missing health URL for {provider}"

    def test_urls_are_https(self):
        for provider, url in PROVIDER_HEALTH_URLS.items():
            assert url.startswith("https://"), f"Non-HTTPS URL for {provider}: {url}"


class TestCategories:
    """Tests for CATEGORIES list."""

    def test_all_used_categories_listed(self):
        used = {ds.category for ds in DATA_SOURCES}
        for cat in used:
            assert cat in CATEGORIES, f"Category {cat} used but not in CATEGORIES list"
