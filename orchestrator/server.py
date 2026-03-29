import asyncio
import logging
from typing import Any

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

from orchestrator.sse import QueueSSEEmitter
from orchestrator.models import TaskStatus, TraceMetrics, TracePayload

logger = logging.getLogger("masa.server")
logging.basicConfig(level=logging.INFO)

app = FastAPI(title="MASA Orchestrator", version="2.0.0")

# Enable CORS for local console
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:3200", "http://127.0.0.1:3200"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Global emitter instance
emitter = QueueSSEEmitter()

class ActionRequest(BaseModel):
    action: str
    payload: dict[str, Any] | None = None

@app.get("/events")
async def sse_events(request: Request):
    """
    Server-Sent Events endpoint.
    Streams event_task_status, attempt_start, attempt_result, and escalation to the Console.
    """
    async def event_generator():
        queue = emitter.connect()
        try:
            async for chunk in emitter.stream(queue):
                # If client disconnects, request.is_disconnected() might be true
                if await request.is_disconnected():
                    break
                yield chunk
        finally:
            emitter.disconnect(queue)

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
        }
    )

@app.post("/tasks/{task_id}/action")
async def task_action(task_id: str, req: ActionRequest):
    """
    Handle operator commands for an escalated task.
    e.g., {"action": "override_approve"}, {"action": "requeue"}
    """
    # This is a stub for the Operator intervention loop.
    # In a full implementation, this would signal a waiting Python task or update a DB.
    logger.info("Received action '%s' for task %s", req.action, task_id)

    # For now, just emit a task status change to show the UI works
    if req.action == "override_approve":
        await emitter.emit_task_status(task_id, TaskStatus.SUCCEEDED)
    elif req.action == "requeue":
        await emitter.emit_task_status(task_id, TaskStatus.PENDING)

    return {"status": "ok", "task_id": task_id, "action": req.action}

@app.post("/test/trigger")
async def trigger_test_events():
    """
    Utility endpoint to fire test events into the SSE stream without
    running the real orchestrator Loop, for UI testing.
    """
    task_id = "TSK-TEST"
    await emitter.emit_task_status(task_id, TaskStatus.RUNNING)
    await asyncio.sleep(0.5)
    await emitter.emit_attempt_start(task_id, 1, "EXPLORATION")
    await asyncio.sleep(1.0)
    await emitter.emit_attempt_result(task_id, 1, False, "PydanticValidationError", "Missing confidence")
    await asyncio.sleep(0.5)
    await emitter.emit_task_status(task_id, TaskStatus.FIXING)
    await asyncio.sleep(1.0)
    await emitter.emit_attempt_start(task_id, 2, "FALLBACK")
    await asyncio.sleep(1.0)
    await emitter.emit_escalation(
        task_id,
        TracePayload(
            task_id=task_id,
            worker_objective="Test escalation path for UI verification",
            error_type="JSONParseError",
            error_message="JSON parse error: Expecting value at line 1 column 1",
            metrics=TraceMetrics(ttft=85.0, tps=22.5, cost=0.014),
            attempted_reasoning=[
                "Issued literature_search for the objective",
                "Received malformed Worker JSON",
                "Escalated after repeated parse failure",
            ],
        ),
    )
    await asyncio.sleep(0.5)
    await emitter.emit_task_status(task_id, TaskStatus.ESCALATED)
    return {"status": "events triggered"}

if __name__ == "__main__":
    import uvicorn
    uvicorn.run("orchestrator.server:app", host="0.0.0.0", port=3201, reload=True)
