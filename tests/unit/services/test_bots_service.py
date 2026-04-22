"""Unit tests for ``bots_service`` (ARCH-C1 Phase 2b PR-1).

Covers the two static read-only helpers extracted in this PR:
``list_strategies`` (returns the ``StrategyRegistry.list_available()``
catalog) and ``list_data_sources`` (returns the
``{"sources": [...], "defaults": [...]}`` shape mirroring the router
response verbatim).

These helpers are pure — no DB, no HTTP, no FastAPI — so the tests
exercise the service functions directly without any fixtures beyond
the module-level ``src.strategy`` / ``src.data.data_source_registry``
imports.
"""

from __future__ import annotations

from src.services import bots_service


class TestListStrategies:
    def test_returns_a_non_empty_list(self) -> None:
        strategies = bots_service.list_strategies()

        assert isinstance(strategies, list)
        assert len(strategies) > 0

    def test_each_entry_has_expected_keys(self) -> None:
        strategies = bots_service.list_strategies()

        expected_keys = {"name", "description", "param_schema"}
        for strategy in strategies:
            assert expected_keys.issubset(strategy.keys()), (
                f"Missing keys in strategy entry: {strategy}"
            )

    def test_matches_strategy_registry_output(self) -> None:
        from src.strategy import StrategyRegistry

        assert bots_service.list_strategies() == StrategyRegistry.list_available()


class TestListDataSources:
    def test_returns_dict_with_sources_and_defaults(self) -> None:
        result = bots_service.list_data_sources()

        assert isinstance(result, dict)
        assert "sources" in result
        assert "defaults" in result
        assert isinstance(result["sources"], list)
        assert isinstance(result["defaults"], list)

    def test_sources_are_plain_dicts(self) -> None:
        result = bots_service.list_data_sources()

        assert len(result["sources"]) > 0
        for source in result["sources"]:
            assert isinstance(source, dict)
            assert "id" in source
            assert "name" in source

    def test_defaults_reference_existing_source_ids(self) -> None:
        result = bots_service.list_data_sources()

        source_ids = {src["id"] for src in result["sources"]}
        for default_id in result["defaults"]:
            assert default_id in source_ids, (
                f"Default source id '{default_id}' not in sources list"
            )
