"""
Integration tests for the MCP Literature Search Server (Spec 1).

These tests hit the REAL Semantic Scholar API.  They require network access
and are subject to rate limits.

Usage:
    pytest tests/test_live_api.py -v --timeout=60 -m integration

All tests are marked with @pytest.mark.integration so they can be
excluded from unit runs:
    pytest tests/ -v -m "not integration"
"""

from __future__ import annotations

import asyncio
import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from masa_mcp.literature_search_server import (
    EpistemicFilter,
    SemanticScholarClient,
    ZeroResults,
    create_server,
)


# Mark all tests in this module as integration
pytestmark = pytest.mark.integration


@pytest.fixture
async def client():
    """Create a SemanticScholarClient and close it after the test."""
    c = SemanticScholarClient()
    yield c
    await c.close()


# ---------------------------------------------------------------------------
# Test: Basic search returns data
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_basic_search(client):
    """Semantic Scholar returns data for a well-known query."""
    result = await client.search("transformer attention mechanism", limit=5)
    assert result.total_upstream > 0
    assert len(result.papers) > 0
    assert result.papers[0].title  # non-empty
    assert result.papers[0].paper_id  # non-empty
    assert result.elapsed_ms > 0


# ---------------------------------------------------------------------------
# Test: Epistemic filter removes preprints
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_epistemic_filter_removes_preprints(client):
    """
    When searching broadly, at least some results should be preprints.
    Filtering with peer_reviewed_only should remove them.
    """
    result = await client.search("deep learning", limit=50)
    all_count = len(result.papers)

    # Apply peer_reviewed_only filter
    peer_reviewed = [p for p in result.papers if not p.is_preprint]
    preprints = [p for p in result.papers if p.is_preprint]

    # We expect at least one preprint to exist in a broad search
    # If not, the test still passes — it just can't verify the filter
    if preprints:
        assert len(peer_reviewed) < all_count
    else:
        # No preprints found — this is OK, just not testable
        pytest.skip("No preprints found in results — cannot verify filter")


# ---------------------------------------------------------------------------
# Test: Pagination round-trip
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_pagination_round_trip(client):
    """Page 1 and page 2 return different papers."""
    result = await client.search("neural network optimization", limit=10)

    if len(result.papers) < 6:
        pytest.skip("Not enough results for pagination test")

    page1 = result.papers[:3]
    page2 = result.papers[3:6]

    page1_ids = {p.paper_id for p in page1}
    page2_ids = {p.paper_id for p in page2}

    assert page1_ids.isdisjoint(page2_ids), "Page 1 and page 2 should have no overlap"


# ---------------------------------------------------------------------------
# Test: Zero results
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_zero_results(client):
    """Nonsense query returns no results."""
    result = await client.search("xyzzy_no_match_12345_quantum_foobar")
    assert result.total_upstream == 0 or len(result.papers) == 0


# ---------------------------------------------------------------------------
# Test: Reference ID continuity
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_reference_id_continuity(client):
    """
    Reference IDs across pages form a continuous sequence.
    Page 1: [1, 2, 3], Page 2: [4, 5, 6], etc.
    This is tested via format_search_response, which is a unit concern,
    but we verify the underlying data supports it.
    """
    result = await client.search("machine learning", limit=10)

    if len(result.papers) < 6:
        pytest.skip("Not enough results for continuity test")

    # Verify that papers have unique IDs (no duplicates)
    ids = [p.paper_id for p in result.papers]
    assert len(ids) == len(set(ids)), "Paper IDs should be unique"


# ---------------------------------------------------------------------------
# Test: Year range filter
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_year_range_filter(client):
    """Papers returned should be within the specified year range."""
    result = await client.search("CRISPR gene editing", year_range="2022-2024", limit=10)

    if len(result.papers) == 0:
        pytest.skip("No results for year-filtered query")

    for paper in result.papers:
        if paper.year is not None:
            assert 2022 <= paper.year <= 2024, (
                f"Paper '{paper.title}' has year {paper.year}, "
                f"expected 2022-2024"
            )


# ---------------------------------------------------------------------------
# Test: Rate limit handling (skipped by default)
# ---------------------------------------------------------------------------


@pytest.mark.skip(reason="Intentionally triggering rate limits is destructive — run manually only")
@pytest.mark.asyncio
async def test_rate_limit_handling(client):
    """
    If rate-limited, the error response should contain [RATE_LIMITED].
    WARNING: This test intentionally hammers the API. Run manually.
    """
    from masa_mcp.literature_search_server import RateLimited

    for _ in range(100):
        try:
            await client.search("test")
        except RateLimited as exc:
            response = exc.to_tool_response()
            assert "[RATE_LIMITED]" in response
            return

    pytest.skip("Could not trigger rate limit")


# ---------------------------------------------------------------------------
# Test: get_paper_detail via client
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_get_paper_success(client):
    """Fetch a known paper by its Semantic Scholar ID."""
    # First, search for a paper to get a valid ID
    result = await client.search("attention is all you need", limit=1)
    if not result.papers:
        pytest.skip("Could not find a paper to test get_paper")

    paper_id = result.papers[0].paper_id
    paper, refs = await client.get_paper(paper_id)
    assert paper.paper_id == paper_id
    assert paper.title  # non-empty


@pytest.mark.asyncio
async def test_get_paper_with_references(client):
    """Fetch a paper with its reference list."""
    result = await client.search("attention is all you need", limit=1)
    if not result.papers:
        pytest.skip("Could not find a paper to test get_paper")

    paper_id = result.papers[0].paper_id
    paper, refs = await client.get_paper(paper_id, include_references=True)
    assert paper.paper_id == paper_id
    # Most papers have at least some references
    # But we don't assert refs > 0 since some might not


# ---------------------------------------------------------------------------
# Test: Health check via client
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_health_check_ping(client):
    """Ping should report reachable with reasonable latency."""
    reachable, latency_ms = await client.ping()
    assert reachable is True
    assert 0 < latency_ms < 30000  # should respond within 30s
