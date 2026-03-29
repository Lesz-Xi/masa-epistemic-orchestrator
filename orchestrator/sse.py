"""
MASA Orchestrator — SSE Event Emitter
=======================================

Server-Sent Events bridge between the Orchestrator and the Operator Console.

Events are typed and JSON-serialized to match the SSEEvent union type
defined in the Console's types.ts. The emitter supports both real SSE
connections (via asyncio queues) and a null emitter for headless/test use.

Transport: HTTP GET /events → text/event-stream
Port: MASA_SSE_PORT (default 3201)
"""

from __future__ import annotations

import asyncio
import json
import logging
from abc import ABC, abstractmethod
from datetime import datetime, timezone
from typing import Any, Optional

from orchestrator.models import TaskStatus, TracePayload

logger = logging.getLogger("masa.sse")


# ---------------------------------------------------------------------------
# Event types — must match console/src/lib/types.ts SSEEvent union
# ---------------------------------------------------------------------------

EVENT_TASK_STATUS = "task:status"
EVENT_ATTEMPT_START = "attempt:start"
EVENT_ATTEMPT_RESULT = "attempt:result"
EVENT_ESCALATION = "escalation"
EVENT_HEARTBEAT = "heartbeat"


# ---------------------------------------------------------------------------
# Abstract SSE interface
# ---------------------------------------------------------------------------


class SSEEmitter(ABC):
    """
    Abstract interface for emitting Server-Sent Events.

    Concrete implementations:
      - QueueSSEEmitter: production emitter backed by asyncio queues
      - NullSSEEmitter: no-op for headless execution and tests
    """

    @abstractmethod
    async def emit(self, event_type: str, data: dict[str, Any]) -> None:
        """Emit a single SSE event."""
        ...

    async def emit_task_status(
        self, task_id: str, status: TaskStatus,
    ) -> None:
        """Emit a task status change event."""
        await self.emit(EVENT_TASK_STATUS, {
            "task_id": task_id,
            "status": status.value if isinstance(status, TaskStatus) else status,
            "timestamp": _now_iso(),
        })

    async def emit_attempt_start(
        self, task_id: str, attempt_number: int, mode: str,
    ) -> None:
        """Emit when a Worker attempt begins."""
        await self.emit(EVENT_ATTEMPT_START, {
            "task_id": task_id,
            "attempt_number": attempt_number,
            "mode": mode,
            "timestamp": _now_iso(),
        })

    async def emit_attempt_result(
        self,
        task_id: str,
        attempt_number: int,
        passed: bool,
        error_type: Optional[str] = None,
        error_msg: Optional[str] = None,
    ) -> None:
        """Emit the result of a Worker attempt (pass/fail)."""
        payload: dict[str, Any] = {
            "task_id": task_id,
            "attempt_number": attempt_number,
            "passed": passed,
            "timestamp": _now_iso(),
        }
        if error_type:
            payload["error_type"] = error_type
        if error_msg:
            payload["error_msg"] = error_msg[:500]  # Truncate for SSE safety
        await self.emit(EVENT_ATTEMPT_RESULT, payload)

    async def emit_escalation(
        self, task_id: str, payload: TracePayload,
    ) -> None:
        """Emit a full escalation payload for the Operator Console."""
        await self.emit(EVENT_ESCALATION, {
            "task_id": task_id,
            "payload": {
                "taskId": payload.task_id,
                "workerObjective": payload.worker_objective,
                "errorType": payload.error_type,
                "errorMessage": payload.error_message,
                "metrics": payload.metrics.model_dump(mode="json"),
                "attemptedReasoning": payload.attempted_reasoning,
            },
            "timestamp": _now_iso(),
        })

    async def emit_heartbeat(self) -> None:
        """Emit a keep-alive heartbeat."""
        await self.emit(EVENT_HEARTBEAT, {
            "timestamp": _now_iso(),
        })


# ---------------------------------------------------------------------------
# Production emitter — backed by asyncio queues
# ---------------------------------------------------------------------------


class QueueSSEEmitter(SSEEmitter):
    """
    Production SSE emitter that fans out events to connected clients.

    Each connected client gets its own asyncio.Queue. Events are
    serialized as `event: <type>\ndata: <json>\n\n` per the SSE spec.

    Usage with aiohttp/Starlette:
        emitter = QueueSSEEmitter()
        queue = emitter.connect()
        # In the SSE endpoint handler:
        async for line in emitter.stream(queue):
            yield line
        emitter.disconnect(queue)
    """

    def __init__(self, max_queue_size: int = 256) -> None:
        self._clients: list[asyncio.Queue[str]] = []
        self._max_queue_size = max_queue_size
        self._event_count = 0

    @property
    def client_count(self) -> int:
        """Number of currently connected SSE clients."""
        return len(self._clients)

    @property
    def event_count(self) -> int:
        """Total events emitted since startup."""
        return self._event_count

    def connect(self) -> asyncio.Queue[str]:
        """Register a new SSE client and return its queue."""
        queue: asyncio.Queue[str] = asyncio.Queue(maxsize=self._max_queue_size)
        self._clients.append(queue)
        logger.info("SSE client connected (total: %d)", len(self._clients))
        return queue

    def disconnect(self, queue: asyncio.Queue[str]) -> None:
        """Remove a disconnected client's queue."""
        try:
            self._clients.remove(queue)
            logger.info("SSE client disconnected (total: %d)", len(self._clients))
        except ValueError:
            pass  # Already removed

    async def emit(self, event_type: str, data: dict[str, Any]) -> None:
        """
        Serialize and fan out an event to all connected clients.

        Dropped events (full queues) are logged but don't block the pipeline.
        """
        self._event_count += 1
        serialized = _format_sse(event_type, data)

        logger.debug("SSE emit: %s → %d clients", event_type, len(self._clients))

        stale: list[asyncio.Queue[str]] = []
        for queue in self._clients:
            try:
                queue.put_nowait(serialized)
            except asyncio.QueueFull:
                logger.warning("SSE client queue full — dropping event")
                stale.append(queue)

        # Prune stale clients whose queues are permanently full
        for q in stale:
            self.disconnect(q)

    async def stream(self, queue: asyncio.Queue[str]):
        """
        Async generator that yields SSE-formatted strings from a client queue.

        Usage in an HTTP handler:
            async for chunk in emitter.stream(queue):
                response.write(chunk.encode())
        """
        try:
            while True:
                chunk = await queue.get()
                yield chunk
        except asyncio.CancelledError:
            logger.debug("SSE stream cancelled")
            raise


# ---------------------------------------------------------------------------
# Null emitter — for headless execution and tests
# ---------------------------------------------------------------------------


class NullSSEEmitter(SSEEmitter):
    """
    No-op SSE emitter for headless execution and unit tests.

    Silently discards all events. Optionally records them for test assertions.
    """

    def __init__(self, record: bool = False) -> None:
        self._record = record
        self._events: list[tuple[str, dict[str, Any]]] = []

    @property
    def events(self) -> list[tuple[str, dict[str, Any]]]:
        """Recorded events (only populated if record=True)."""
        return self._events

    async def emit(self, event_type: str, data: dict[str, Any]) -> None:
        if self._record:
            self._events.append((event_type, data))


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _now_iso() -> str:
    """UTC ISO 8601 timestamp."""
    return datetime.now(timezone.utc).isoformat()


def _format_sse(event_type: str, data: dict[str, Any]) -> str:
    """
    Format an event per the SSE specification.

    Output:
        event: <type>
        data: <json>
        <blank line>
    """
    json_str = json.dumps(data, default=str)
    return f"event: {event_type}\ndata: {json_str}\n\n"
