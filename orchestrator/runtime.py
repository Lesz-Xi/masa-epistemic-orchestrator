"""
MASA Orchestrator — Task-scoped runtime boundary.

Owns the authoritative served-reference ledger for a task and provides
the concrete handoff from MCP tool output to the execute_task loop.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Optional

from clients.base import LLMClient
from orchestrator.models import ScientificTask, ServedReference, TaskExecutionLog
from orchestrator.orchestrator import execute_task
from orchestrator.reference_ledger import ServedReferenceLedger
from orchestrator.sse import SSEEmitter


@dataclass
class TaskExecutionSession:
    """
    Runtime adapter that accumulates authoritative tool provenance for one task.

    Callers ingest server-owned MCP tool responses as they happen, then execute
    the Worker against an immutable snapshot of the resulting ledger.
    """

    task: ScientificTask
    worker_client: LLMClient
    fixer_client: LLMClient
    emitter: Optional[SSEEmitter] = None
    worker_model: Optional[str] = None
    fixer_model: Optional[str] = None
    _ledger: ServedReferenceLedger = field(default_factory=ServedReferenceLedger)

    def ingest_tool_output(self, tool_name: str, tool_output: Any) -> None:
        """
        Merge a server-owned MCP tool response into the authoritative ledger.

        Accepted shapes:
        - plain text strings
        - stdio/SDK content arrays: [TextContent(...)]
        - MCP result envelopes: {"content": [{"type": "text", "text": "..."}]}
        """
        self._ledger.ingest(tool_name, extract_tool_text(tool_output))

    def served_references(self) -> dict[int, ServedReference]:
        """Expose a read-only snapshot of references served to the Worker."""
        return self._ledger.snapshot()

    async def execute(self) -> TaskExecutionLog:
        """Run the task with the current authoritative served-reference snapshot."""
        return await execute_task(
            task=self.task,
            worker_client=self.worker_client,
            fixer_client=self.fixer_client,
            served_references=self.served_references(),
            emitter=self.emitter,
            worker_model=self.worker_model,
            fixer_model=self.fixer_model,
        )


def extract_tool_text(tool_output: Any) -> str:
    """
    Normalize MCP tool results from Codex/Claude transports into plain text.

    This lets the orchestrator ingest server-owned tool output without caring
    whether the caller came from stdio, HTTP JSON-RPC, or an in-process helper.
    """
    if isinstance(tool_output, str):
        return tool_output

    if isinstance(tool_output, dict):
        if "content" in tool_output:
            return extract_tool_text(tool_output["content"])
        text = tool_output.get("text")
        if tool_output.get("type") == "text" and isinstance(text, str):
            return text
        raise ValueError("Unsupported MCP tool output dict shape; expected text content.")

    if isinstance(tool_output, (list, tuple)):
        chunks: list[str] = []
        for item in tool_output:
            if isinstance(item, str):
                chunks.append(item)
                continue
            if isinstance(item, dict):
                if item.get("type") == "text" and isinstance(item.get("text"), str):
                    chunks.append(item["text"])
                    continue
                raise ValueError("Unsupported MCP content block dict; expected text content.")

            block_type = getattr(item, "type", None)
            block_text = getattr(item, "text", None)
            if block_type == "text" and isinstance(block_text, str):
                chunks.append(block_text)
                continue

            raise ValueError("Unsupported MCP content block object; expected text content.")

        if not chunks:
            raise ValueError("Tool output did not contain any text content.")
        return "\n".join(chunks)

    content = getattr(tool_output, "content", None)
    if content is not None:
        return extract_tool_text(content)

    raise ValueError("Unsupported MCP tool output; expected string or text content blocks.")
