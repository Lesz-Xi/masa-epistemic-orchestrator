"""
Minimal end-to-end example showing the shared runtime boundary.
"""

from __future__ import annotations

import asyncio

from clients.mock_client import MockClient
from masa_mcp.literature_search_server import Paper, format_search_response
from orchestrator.models import ScientificTask
from orchestrator.runtime import TaskExecutionSession


def _make_paper() -> Paper:
    return Paper(
        paper_id="paper-1",
        title="BRCA1 and homologous recombination",
        abstract="BRCA1 plays a central role in homologous recombination repair.",
        authors=["Author A"],
        year=2024,
        venue="Nature",
        citation_count=10,
        is_open_access=True,
        url="https://example.com/paper-1",
        publication_types=["JournalArticle"],
    )


async def main() -> None:
    task = ScientificTask(
        task_id="example-001",
        objective="Identify key factors in BRCA1 tumor suppression",
    )
    worker = MockClient()
    fixer = MockClient()
    session = TaskExecutionSession(task=task, worker_client=worker, fixer_client=fixer)

    tool_text = format_search_response(
        papers=[_make_paper()],
        chunk_offset=0,
        total_after_filter=1,
        total_upstream=1,
        query="BRCA1 tumor suppression",
        epistemic_filter="peer_reviewed_only",
        elapsed_ms=120.0,
        preprints_removed=0,
    )
    session.ingest_tool_output("literature_search", tool_text)

    worker.enqueue_json(
        {
            "task_id": task.task_id,
            "summary": "BRCA1 stabilizes genome integrity through homologous recombination repair.",
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
    )

    log = await session.execute()
    print(log.final_result.model_dump_json(indent=2))


if __name__ == "__main__":
    asyncio.run(main())
