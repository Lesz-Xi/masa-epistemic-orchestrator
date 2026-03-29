"""
Unit tests for served reference ledger parsing.
"""

from __future__ import annotations

import pytest

from masa_mcp.literature_search_server import Paper, format_paper_detail_response, format_search_response
from orchestrator.reference_ledger import (
    ServedReferenceLedger,
    parse_literature_search_response,
)


def _make_paper(paper_id: str, title: str) -> Paper:
    return Paper(
        paper_id=paper_id,
        title=title,
        abstract=f"Abstract for {title}",
        authors=["Author A", "Author B"],
        year=2024,
        venue="Nature",
        citation_count=10,
        is_open_access=True,
        url=f"https://example.com/{paper_id}",
        publication_types=["JournalArticle"],
    )


class TestReferenceLedgerParsing:
    def test_parse_literature_search_response_extracts_authoritative_ledger(self):
        response_text = format_search_response(
            papers=[_make_paper("paper-1", "Paper 1"), _make_paper("paper-2", "Paper 2")],
            chunk_offset=0,
            total_after_filter=2,
            total_upstream=2,
            query="oncology",
            epistemic_filter="peer_reviewed_only",
            elapsed_ms=120.0,
            preprints_removed=0,
        )

        ledger = parse_literature_search_response(response_text)

        assert sorted(ledger) == [1, 2]
        assert ledger[1].paper_id == "paper-1"
        assert ledger[2].title == "Paper 2"

    def test_ledger_ignores_verification_only_tool_output(self):
        ledger = ServedReferenceLedger()
        detail_text = format_paper_detail_response(_make_paper("paper-1", "Paper 1"), [], elapsed_ms=30.0)

        ledger.ingest("get_paper_detail", detail_text)

        assert ledger.snapshot() == {}

    def test_ledger_rejects_reference_id_collisions(self):
        ledger = ServedReferenceLedger()
        first_response = format_search_response(
            papers=[_make_paper("paper-1", "Paper 1")],
            chunk_offset=0,
            total_after_filter=1,
            total_upstream=1,
            query="oncology",
            epistemic_filter="peer_reviewed_only",
            elapsed_ms=120.0,
            preprints_removed=0,
        )
        second_response = first_response.replace("Semantic Scholar ID: paper-1", "Semantic Scholar ID: paper-X")

        ledger.ingest("literature_search", first_response)

        with pytest.raises(ValueError, match="Reference ID collision"):
            ledger.ingest("literature_search", second_response)
