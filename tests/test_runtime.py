"""
Runtime boundary tests for task-scoped served-reference ledger wiring.
"""

from __future__ import annotations

import pytest
from mcp.types import TextContent

from clients.mock_client import MockClient
from masa_mcp.literature_search_server import Paper, format_paper_detail_response, format_search_response
from orchestrator.models import ScientificTask, TaskStatus
from orchestrator.orchestrator import execute_task
from orchestrator.runtime import TaskExecutionSession, extract_tool_text


def _make_task() -> ScientificTask:
    return ScientificTask(
        task_id="runtime-001",
        objective="Identify key factors in BRCA1 tumor suppression",
        max_attempts=2,
    )


def _make_valid_result(task_id: str) -> dict:
    return {
        "task_id": task_id,
        "summary": "BRCA1 plays a central role in homologous recombination and genome stability maintenance.",
        "evidence": [
            {
                "reference_id": 1,
                "claim": "BRCA1 is essential for homologous recombination repair.",
                "strength": "strong",
            }
        ],
        "confidence": 0.82,
        "reasoning_chain": [
            "Used the served literature_search references.",
            "Identified homologous recombination as the dominant mechanism.",
        ],
        "cited_reference_ids": [1],
    }


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


class TestRuntimeBoundary:
    def test_extract_tool_text_accepts_stdio_content_blocks(self):
        response_text = format_search_response(
            papers=[_make_paper("paper-1", "Paper 1")],
            chunk_offset=0,
            total_after_filter=1,
            total_upstream=1,
            query="oncology",
            epistemic_filter="peer_reviewed_only",
            elapsed_ms=120.0,
            preprints_removed=0,
        )

        normalized = extract_tool_text([TextContent(type="text", text=response_text)])

        assert "Semantic Scholar ID: paper-1" in normalized

    def test_extract_tool_text_accepts_claude_style_content_envelope(self):
        response_text = format_search_response(
            papers=[_make_paper("paper-1", "Paper 1")],
            chunk_offset=0,
            total_after_filter=1,
            total_upstream=1,
            query="oncology",
            epistemic_filter="peer_reviewed_only",
            elapsed_ms=120.0,
            preprints_removed=0,
        )

        normalized = extract_tool_text(
            {"content": [{"type": "text", "text": response_text}]}
        )

        assert "Semantic Scholar ID: paper-1" in normalized

    @pytest.mark.asyncio
    async def test_execute_task_fails_fast_without_served_reference_context(self):
        task = _make_task()
        worker = MockClient()
        fixer = MockClient()

        with pytest.raises(ValueError, match="authoritative literature_search reference ledger"):
            await execute_task(
                task=task,
                worker_client=worker,
                fixer_client=fixer,
                served_references={},
            )

    @pytest.mark.asyncio
    async def test_task_execution_session_ingests_literature_search_and_executes(self):
        task = _make_task()
        worker = MockClient()
        fixer = MockClient()
        session = TaskExecutionSession(task=task, worker_client=worker, fixer_client=fixer)

        response_text = format_search_response(
            papers=[_make_paper("paper-1", "Paper 1")],
            chunk_offset=0,
            total_after_filter=1,
            total_upstream=1,
            query="oncology",
            epistemic_filter="peer_reviewed_only",
            elapsed_ms=120.0,
            preprints_removed=0,
        )
        session.ingest_tool_output("literature_search", response_text)

        worker.enqueue_json(_make_valid_result(task.task_id))

        log = await session.execute()

        assert sorted(session.served_references()) == [1]
        assert log.final_result is not None
        assert log.final_result.task_id == task.task_id
        assert task.status == TaskStatus.SUCCEEDED

    @pytest.mark.asyncio
    async def test_task_execution_session_ignores_verification_only_tool_output(self):
        task = _make_task()
        worker = MockClient()
        fixer = MockClient()
        session = TaskExecutionSession(task=task, worker_client=worker, fixer_client=fixer)

        detail_text = format_paper_detail_response(_make_paper("paper-1", "Paper 1"), [], elapsed_ms=30.0)
        session.ingest_tool_output("get_paper_detail", detail_text)

        with pytest.raises(ValueError, match="authoritative literature_search reference ledger"):
            await session.execute()

    @pytest.mark.asyncio
    async def test_task_execution_session_accepts_claude_style_tool_payload(self):
        task = _make_task()
        worker = MockClient()
        fixer = MockClient()
        session = TaskExecutionSession(task=task, worker_client=worker, fixer_client=fixer)

        response_text = format_search_response(
            papers=[_make_paper("paper-1", "Paper 1")],
            chunk_offset=0,
            total_after_filter=1,
            total_upstream=1,
            query="oncology",
            epistemic_filter="peer_reviewed_only",
            elapsed_ms=120.0,
            preprints_removed=0,
        )
        session.ingest_tool_output(
            "literature_search",
            {"content": [{"type": "text", "text": response_text}]},
        )

        worker.enqueue_json(_make_valid_result(task.task_id))

        log = await session.execute()

        assert log.final_result is not None
        assert log.final_result.task_id == task.task_id
