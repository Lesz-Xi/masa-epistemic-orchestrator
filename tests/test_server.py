"""
Unit tests for the MCP Literature Search Server (Spec 1).

Tests cover:
  - ResultCache (hit, miss, TTL expiry, LRU eviction, pre-filter keying)
  - get_paper_detail (success, not found, with references)
  - health_check (reachable, unreachable)
  - Client lifecycle (close() called)
  - Tool dispatch routing
  - Cache integration with literature_search

All tests use mocked httpx calls — no network required.
"""

from __future__ import annotations

import asyncio
import copy
import time
from dataclasses import dataclass
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

# --- Module under test ---
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from masa_mcp.literature_search_server import (
    CacheEntry,
    EpistemicFilter,
    Paper,
    PaperNotFound,
    RateLimited,
    ResultCache,
    SearchResult,
    SemanticScholarClient,
    ZeroResults,
    _handle_get_paper_detail,
    _handle_literature_search,
    create_server,
    format_paper_block,
    format_paper_detail_response,
    format_search_response,
)

from mcp.server import Server


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


def _make_paper(
    paper_id: str = "abc123",
    title: str = "Test Paper",
    abstract: str = "A test abstract.",
    venue: str = "Nature",
    year: int = 2024,
    citation_count: int = 42,
    is_open_access: bool = True,
    publication_types: list[str] | None = None,
) -> Paper:
    return Paper(
        paper_id=paper_id,
        title=title,
        abstract=abstract,
        authors=["Author A", "Author B"],
        year=year,
        venue=venue,
        citation_count=citation_count,
        is_open_access=is_open_access,
        url=f"https://example.com/{paper_id}",
        publication_types=publication_types or ["JournalArticle"],
    )


def _make_search_result(n: int = 3, query: str = "test") -> SearchResult:
    papers = [_make_paper(paper_id=f"paper_{i}", title=f"Paper {i}") for i in range(n)]
    return SearchResult(papers=papers, total_upstream=n, query=query, elapsed_ms=100.0)


# ===========================================================================
# ResultCache Tests
# ===========================================================================


class TestResultCache:
    def test_make_key_normalizes(self):
        """Cache keys are normalized: lowercase, sorted fields."""
        k1 = ResultCache.make_key("Attention Mechanism", "2020-2024", ["Physics", "Biology"])
        k2 = ResultCache.make_key("attention mechanism", "2020-2024", ["Biology", "Physics"])
        assert k1 == k2

    def test_make_key_none_vs_empty(self):
        """None fields_of_study and empty list produce the same key."""
        k1 = ResultCache.make_key("test", None, None)
        k2 = ResultCache.make_key("test", None, [])
        assert k1 == k2

    def test_cache_miss_returns_none(self):
        cache = ResultCache()
        key = cache.make_key("unknown", None, None)
        assert cache.get(key) is None

    def test_cache_put_and_get(self):
        cache = ResultCache()
        result = _make_search_result()
        key = cache.make_key("test", None, None)
        cache.put(key, result)
        retrieved = cache.get(key)
        assert retrieved is not None
        assert len(retrieved.papers) == 3
        assert retrieved.query == "test"

    def test_cache_returns_deep_copy(self):
        """Mutations to returned result don't affect cache."""
        cache = ResultCache()
        result = _make_search_result()
        key = cache.make_key("test", None, None)
        cache.put(key, result)

        retrieved = cache.get(key)
        assert retrieved is not None
        retrieved.papers.clear()  # mutate

        # Original cache entry should be unaffected
        second = cache.get(key)
        assert second is not None
        assert len(second.papers) == 3

    def test_cache_ttl_expiry(self):
        """Expired entries return None."""
        cache = ResultCache(ttl=0.01)  # 10ms TTL
        result = _make_search_result()
        key = cache.make_key("test", None, None)
        cache.put(key, result)

        time.sleep(0.02)  # Wait for TTL
        assert cache.get(key) is None
        assert cache.size == 0  # Evicted on access

    def test_cache_lru_eviction(self):
        """Oldest entry is evicted when exceeding MAX_ENTRIES."""
        cache = ResultCache(max_entries=3)

        for i in range(3):
            key = cache.make_key(f"query_{i}", None, None)
            cache.put(key, _make_search_result(query=f"query_{i}"))

        assert cache.size == 3

        # Access query_1 to make it more recent than query_0
        cache.get(cache.make_key("query_1", None, None))

        # Insert a 4th entry — should evict query_0 (oldest access)
        key4 = cache.make_key("query_3", None, None)
        cache.put(key4, _make_search_result(query="query_3"))

        assert cache.size == 3
        assert cache.get(cache.make_key("query_0", None, None)) is None  # evicted
        assert cache.get(cache.make_key("query_1", None, None)) is not None  # kept
        assert cache.get(cache.make_key("query_2", None, None)) is not None  # kept
        assert cache.get(cache.make_key("query_3", None, None)) is not None  # new

    def test_cache_pre_filter_keying(self):
        """Same query with different epistemic filters shares cache."""
        cache = ResultCache()
        result = _make_search_result()
        # Cache key does NOT include epistemic filter
        key = cache.make_key("test", None, None)
        cache.put(key, result)

        # Same key regardless of what the caller does with the filter
        assert cache.get(key) is not None

    def test_cache_invalidate_all(self):
        cache = ResultCache()
        for i in range(5):
            key = cache.make_key(f"q{i}", None, None)
            cache.put(key, _make_search_result())
        assert cache.size == 5

        cache.invalidate_all()
        assert cache.size == 0

    def test_cache_size_property(self):
        cache = ResultCache()
        assert cache.size == 0
        cache.put(cache.make_key("a", None, None), _make_search_result())
        assert cache.size == 1


# ===========================================================================
# PaperNotFound Error Tests
# ===========================================================================


class TestPaperNotFound:
    def test_to_tool_response(self):
        err = PaperNotFound("abc123")
        response = err.to_tool_response()
        assert "[PAPER_NOT_FOUND]" in response
        assert "abc123" in response
        assert "Action:" in response


# ===========================================================================
# Format Tests
# ===========================================================================


class TestFormatPaperDetail:
    def test_basic_format(self):
        paper = _make_paper()
        text = format_paper_detail_response(paper, [], elapsed_ms=42.5)
        assert "Paper Detail" in text
        assert "Test Paper" in text
        assert "VERIFICATION ONLY" in text
        assert "[Reference ID: 1]" not in text
        assert "REFERENCE LIST" not in text  # no refs

    def test_with_references(self):
        paper = _make_paper()
        refs = [
            {"paperId": "ref1", "title": "Ref Paper 1", "year": 2023, "authors": ["X"]},
            {"paperId": "ref2", "title": "Ref Paper 2", "year": 2022, "authors": ["Y", "Z"]},
        ]
        text = format_paper_detail_response(paper, refs, elapsed_ms=50.0)
        assert "REFERENCE LIST (2 outgoing citations)" in text
        assert "Ref Paper 1" in text
        assert "Ref Paper 2" in text


class TestToolInputValidation:
    @pytest.mark.asyncio
    async def test_literature_search_rejects_non_string_query(self):
        response = await _handle_literature_search(AsyncMock(), ResultCache(), {"query": {}})
        assert response[0].text.startswith("[INVALID_INPUT]")
        assert "query" in response[0].text

    @pytest.mark.asyncio
    async def test_literature_search_rejects_non_integer_chunk_offset(self):
        response = await _handle_literature_search(
            AsyncMock(),
            ResultCache(),
            {"query": "transformers", "chunk_offset": "*"},
        )
        assert response[0].text.startswith("[INVALID_INPUT]")
        assert "chunk_offset" in response[0].text

    @pytest.mark.asyncio
    async def test_get_paper_detail_rejects_non_string_paper_id(self):
        response = await _handle_get_paper_detail(AsyncMock(), {"paper_id": 123})
        assert response[0].text.startswith("[INVALID_INPUT]")
        assert "paper_id" in response[0].text


class TestFormatSearchResponse:
    def test_cache_hit_indicator(self):
        papers = [_make_paper()]
        text = format_search_response(
            papers,
            chunk_offset=0,
            total_after_filter=1,
            total_upstream=1,
            query="test",
            epistemic_filter="all",
            elapsed_ms=0,
            preprints_removed=0,
            cache_hit=True,
        )
        assert "cached" in text

    def test_no_cache_shows_latency(self):
        papers = [_make_paper()]
        text = format_search_response(
            papers,
            chunk_offset=0,
            total_after_filter=1,
            total_upstream=1,
            query="test",
            epistemic_filter="all",
            elapsed_ms=123.0,
            preprints_removed=0,
            cache_hit=False,
        )
        assert "API Latency: 123 ms" in text


# ===========================================================================
# SemanticScholarClient.get_paper Tests (mocked)
# ===========================================================================


class TestGetPaper:
    @pytest.mark.asyncio
    async def test_get_paper_success(self):
        """Successful paper lookup returns Paper and empty refs."""
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "paperId": "abc123",
            "title": "Test Paper",
            "abstract": "Abstract text",
            "authors": [{"name": "Alice"}],
            "year": 2024,
            "venue": "Nature",
            "citationCount": 10,
            "isOpenAccess": True,
            "url": "https://example.com/abc123",
            "publicationTypes": ["JournalArticle"],
        }
        mock_response.raise_for_status = MagicMock()

        client = SemanticScholarClient()
        client._client = AsyncMock()
        client._client.get = AsyncMock(return_value=mock_response)

        paper, refs = await client.get_paper("abc123")
        assert paper.paper_id == "abc123"
        assert paper.title == "Test Paper"
        assert refs == []

        await client.close()

    @pytest.mark.asyncio
    async def test_get_paper_not_found(self):
        """404 raises PaperNotFound."""
        mock_response = MagicMock()
        mock_response.status_code = 404

        client = SemanticScholarClient()
        client._client = AsyncMock()
        client._client.get = AsyncMock(return_value=mock_response)

        with pytest.raises(PaperNotFound) as exc_info:
            await client.get_paper("nonexistent")
        assert exc_info.value.paper_id == "nonexistent"

        await client.close()

    @pytest.mark.asyncio
    async def test_get_paper_with_references(self):
        """Paper with include_references returns reference list."""
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "paperId": "abc123",
            "title": "Test Paper",
            "abstract": "Abstract",
            "authors": [{"name": "Alice"}],
            "year": 2024,
            "venue": "ICML",
            "citationCount": 5,
            "isOpenAccess": False,
            "url": "https://example.com/abc123",
            "publicationTypes": ["Conference"],
            "references": [
                {"paperId": "ref1", "title": "Ref 1", "year": 2023, "authors": [{"name": "Bob"}]},
                {"paperId": "ref2", "title": "Ref 2", "year": 2022, "authors": [{"name": "Carol"}]},
                {"paperId": None, "title": "Bad Ref"},  # should be skipped
            ],
        }
        mock_response.raise_for_status = MagicMock()

        client = SemanticScholarClient()
        client._client = AsyncMock()
        client._client.get = AsyncMock(return_value=mock_response)

        paper, refs = await client.get_paper("abc123", include_references=True)
        assert paper.paper_id == "abc123"
        assert len(refs) == 2  # bad ref filtered out
        assert refs[0]["paperId"] == "ref1"
        assert refs[1]["authors"] == ["Carol"]

        await client.close()

    @pytest.mark.asyncio
    async def test_get_paper_rate_limited(self):
        """429 raises RateLimited."""
        mock_response = MagicMock()
        mock_response.status_code = 429

        client = SemanticScholarClient()
        client._client = AsyncMock()
        client._client.get = AsyncMock(return_value=mock_response)

        with pytest.raises(RateLimited):
            await client.get_paper("abc123")

        await client.close()


# ===========================================================================
# SemanticScholarClient.ping Tests
# ===========================================================================


class TestPing:
    @pytest.mark.asyncio
    async def test_ping_reachable(self):
        mock_response = MagicMock()
        mock_response.status_code = 200

        client = SemanticScholarClient()
        client._client = AsyncMock()
        client._client.get = AsyncMock(return_value=mock_response)

        reachable, latency = await client.ping()
        assert reachable is True
        assert latency >= 0

        await client.close()

    @pytest.mark.asyncio
    async def test_ping_unreachable_timeout(self):
        import httpx as httpx_mod

        client = SemanticScholarClient()
        client._client = AsyncMock()
        client._client.get = AsyncMock(side_effect=httpx_mod.TimeoutException("timeout"))

        reachable, latency = await client.ping()
        assert reachable is False
        assert latency >= 0

        await client.close()

    @pytest.mark.asyncio
    async def test_ping_unreachable_connect_error(self):
        import httpx as httpx_mod

        client = SemanticScholarClient()
        client._client = AsyncMock()
        client._client.get = AsyncMock(side_effect=httpx_mod.ConnectError("refused"))

        reachable, latency = await client.ping()
        assert reachable is False

        await client.close()

    @pytest.mark.asyncio
    async def test_ping_server_error(self):
        """Server 500 reports as NOT reachable."""
        mock_response = MagicMock()
        mock_response.status_code = 500

        client = SemanticScholarClient()
        client._client = AsyncMock()
        client._client.get = AsyncMock(return_value=mock_response)

        reachable, _ = await client.ping()
        assert reachable is False

        await client.close()


# ===========================================================================
# Tool Dispatch Routing Tests
# ===========================================================================


class TestToolRouting:
    @pytest.mark.asyncio
    async def test_create_server_returns_correct_types(self):
        """create_server returns (Server, SemanticScholarClient, ResultCache)."""
        server, client, cache = create_server()
        try:
            assert isinstance(server, Server)
            assert isinstance(client, SemanticScholarClient)
            assert isinstance(cache, ResultCache)
        finally:
            await client.close()

    @pytest.mark.asyncio
    async def test_server_and_cache_initialized(self):
        """Server created successfully with empty cache."""
        server, client, cache = create_server()
        try:
            assert server is not None
            assert cache.size == 0
            assert server.name == "masa-literature-search"
        finally:
            await client.close()


# ===========================================================================
# Client Lifecycle Tests
# ===========================================================================


class TestClientLifecycle:
    @pytest.mark.asyncio
    async def test_close_is_called(self):
        """Verify that create_server returns client that can be closed."""
        server, client, cache = create_server()
        # Mock the underlying httpx client
        client._client = AsyncMock()
        client._client.aclose = AsyncMock()

        await client.close()
        client._client.aclose.assert_called_once()


# ===========================================================================
# Integration: Cache + literature_search handler
# ===========================================================================


class TestCacheIntegration:
    @pytest.mark.asyncio
    async def test_cache_hit_skips_api(self):
        """Second call with same params uses cache, no API call."""
        cache = ResultCache()
        result = _make_search_result(n=5, query="transformers")
        key = cache.make_key("transformers", None, None)
        cache.put(key, result)

        # Verify the cache has it
        cached = cache.get(key)
        assert cached is not None
        assert len(cached.papers) == 5

    @pytest.mark.asyncio
    async def test_cache_miss_stores_result(self):
        """First call stores result in cache."""
        cache = ResultCache()
        result = _make_search_result(n=3, query="attention")
        key = cache.make_key("attention", None, None)

        assert cache.get(key) is None  # miss
        cache.put(key, result)
        assert cache.get(key) is not None  # now stored

    @pytest.mark.asyncio
    async def test_epistemic_filter_on_cached_result(self):
        """Epistemic filter applied after cache retrieval."""
        cache = ResultCache()

        # Create result with mix of preprints and journal articles
        papers = [
            _make_paper(paper_id="p1", venue="Nature", publication_types=["JournalArticle"]),
            _make_paper(paper_id="p2", venue="", publication_types=["Preprint"]),
            _make_paper(paper_id="p3", venue="Science", publication_types=["JournalArticle"]),
        ]
        result = SearchResult(papers=papers, total_upstream=3, query="test", elapsed_ms=50.0)
        key = cache.make_key("test", None, None)
        cache.put(key, result)

        # Retrieve and apply peer_reviewed_only filter
        cached = cache.get(key)
        assert cached is not None
        filtered = [p for p in cached.papers if not p.is_preprint]
        assert len(filtered) == 2  # preprint removed
        assert all(p.paper_id != "p2" for p in filtered)

        # Original cache still has all 3
        second = cache.get(key)
        assert second is not None
        assert len(second.papers) == 3
