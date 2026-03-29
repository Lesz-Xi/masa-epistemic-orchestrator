"""
Unit tests for the MASA MCP HTTP transport.
"""

from __future__ import annotations

from unittest.mock import AsyncMock

import pytest
from pydantic import ValidationError

from masa_mcp import http_server as mcp_http_server


def _make_http_paper(
    paper_id: str,
    *,
    title: str,
    venue: str = "Nature",
    publication_types: list[str] | None = None,
) -> dict[str, object]:
    return {
        "paperId": paper_id,
        "title": title,
        "abstract": f"Abstract for {title}",
        "authors": [{"name": "Author A"}, {"name": "Author B"}],
        "year": 2024,
        "venue": venue,
        "citationCount": 12,
        "isOpenAccess": True,
        "publicationTypes": publication_types or ["JournalArticle"],
    }


class TestHttpLiteratureSearch:
    @pytest.mark.asyncio
    async def test_execute_literature_search_rejects_invalid_filter(self):
        with pytest.raises(ValidationError):
            await mcp_http_server.execute_literature_search(
                {"query": "oncology", "epistemic_filter": "Peer_Reviewed_Only"}
            )

    @pytest.mark.asyncio
    async def test_execute_literature_search_uses_absolute_offsets(self, monkeypatch):
        raw_papers = [
            _make_http_paper("paper-1", title="Paper 1"),
            _make_http_paper(
                "paper-2",
                title="Paper 2",
                venue="",
                publication_types=["Preprint"],
            ),
            _make_http_paper("paper-3", title="Paper 3"),
            _make_http_paper("paper-4", title="Paper 4"),
        ]
        monkeypatch.setattr(
            mcp_http_server,
            "_search_semantic_scholar",
            AsyncMock(return_value=raw_papers),
        )

        text = await mcp_http_server.execute_literature_search(
            {
                "query": "oncology",
                "epistemic_filter": "peer_reviewed_only",
                "chunk_offset": 1,
            }
        )

        assert "PREPRINTS REMOVED: 1" in text
        assert "SHOWING: 2-3 of 3 after filtering" in text
        assert "REFERENCE IDs ON THIS PAGE: [2, 3]" in text
        assert "[Reference ID: 2]" in text
        assert "[Reference ID: 3]" in text
        assert "All matching papers have been returned." in text

    @pytest.mark.asyncio
    async def test_execute_literature_search_returns_invalid_offset_message(self, monkeypatch):
        monkeypatch.setattr(
            mcp_http_server,
            "_search_semantic_scholar",
            AsyncMock(return_value=[_make_http_paper("paper-1", title="Paper 1")]),
        )

        text = await mcp_http_server.execute_literature_search(
            {"query": "oncology", "chunk_offset": 5}
        )

        assert text.startswith("[INVALID_OFFSET]")
