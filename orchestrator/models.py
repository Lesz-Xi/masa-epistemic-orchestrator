"""
MASA Orchestrator — Domain Models
==================================

All Pydantic models that flow through the orchestration pipeline.
These are the contracts between Worker, Fixer, Orchestrator, and Console.
"""

from __future__ import annotations

from datetime import datetime, timezone
from enum import Enum
from typing import Any, Optional

from pydantic import BaseModel, ConfigDict, Field


# ---------------------------------------------------------------------------
# Task lifecycle
# ---------------------------------------------------------------------------


class TaskStatus(str, Enum):
    PENDING = "pending"
    RUNNING = "running"
    VALIDATING = "validating"
    FIXING = "fixing"
    SUCCEEDED = "succeeded"
    FAILED_TERMINAL = "failed_terminal"
    ESCALATED = "escalated"


class ScientificTask(BaseModel):
    """A unit of work assigned to a Worker agent."""

    model_config = ConfigDict(use_enum_values=True)

    task_id: str = Field(description="Unique identifier — used for PRNG seed derivation")
    objective: str = Field(description="Natural-language objective for the Worker")
    required_tools: list[str] = Field(
        default_factory=lambda: ["literature_search"],
        description="MCP tools the Worker may call",
    )
    output_schema_name: str = Field(
        default="WorkerResult",
        description="Name of the Pydantic model the output must conform to",
    )
    status: TaskStatus = TaskStatus.PENDING
    attempt_count: int = 0
    max_attempts: int = 3
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


# ---------------------------------------------------------------------------
# Worker output — what the LLM must produce
# ---------------------------------------------------------------------------


class EvidenceItem(BaseModel):
    """A single piece of evidence tied to a literature reference."""

    reference_id: int = Field(description="Must match a [Reference ID: N] from literature_search")
    claim: str = Field(description="The specific claim supported by this reference")
    strength: str = Field(
        description="Evidence strength",
        pattern="^(strong|moderate|weak)$",
    )
    quote: Optional[str] = Field(
        default=None,
        description="Direct quote from the abstract, if available",
    )


class WorkerResult(BaseModel):
    """Schema the Worker MUST output. Validated by Pydantic before acceptance."""

    task_id: str
    summary: str = Field(
        description="1-3 sentence summary of findings",
        min_length=10,
        max_length=2000,
    )
    evidence: list[EvidenceItem] = Field(
        description="Evidence items with reference IDs",
        min_length=1,
    )
    confidence: float = Field(
        ge=0.0,
        le=1.0,
        description="Self-assessed confidence 0.0–1.0",
    )
    reasoning_chain: list[str] = Field(
        description="Step-by-step reasoning trace",
        min_length=1,
    )
    cited_reference_ids: list[int] = Field(
        description="[Reference ID: N] values used — must be non-empty",
        min_length=1,
    )


class ServedReference(BaseModel):
    """Authoritative record of a paper served to the Worker during the task."""

    ref_id: int = Field(description="Reference ID exposed to the Worker")
    paper_id: str = Field(description="Stable upstream paper identifier")
    title: Optional[str] = Field(default=None, description="Human-readable paper title, if parsed")
    source_tool: str = Field(default="literature_search")


# ---------------------------------------------------------------------------
# Execution records — immutable audit trail
# ---------------------------------------------------------------------------


class ExecutionConfig(BaseModel):
    """Snapshot of the LLM parameters used for a given attempt."""

    model_config = ConfigDict(frozen=True)

    temperature: float
    top_p: float
    top_k: int
    seed: Optional[int] = None
    response_format: dict[str, str] = Field(default_factory=lambda: {"type": "json_object"})


class AttemptRecord(BaseModel):
    """Immutable record of a single Worker execution attempt."""

    attempt_number: int
    prompt_sent: str
    raw_response: str
    validation_passed: bool
    error_trace: Optional[str] = None
    error_type: Optional[str] = None  # "PydanticValidationError" | "EpistemicBoundaryViolation" | "LogicFailure"
    fixer_diagnostics: Optional[FixerDiagnostics] = None
    rewritten_prompt: Optional[str] = None
    config_used: ExecutionConfig
    timestamp: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    latency_ms: float = 0.0
    tokens_used: int = 0
    ttft_ms: float = 0.0
    total_ms: float = 0.0
    tokens_input: int = 0
    tokens_output: int = 0
    cost_usd: float = 0.0


class FixerDiagnostics(BaseModel):
    """Structured output from the Fixer Agent."""

    failure_point: str
    correction_strategy: str


class FixerOutput(BaseModel):
    """Full Fixer Agent response — parsed from JSON."""

    diagnostics: FixerDiagnostics
    rewritten_prompt: str


# ---------------------------------------------------------------------------
# Escalation payload — sent to the Operator Console
# ---------------------------------------------------------------------------


class TracePayload(BaseModel):
    """Payload streamed to the Operator Console when a task is escalated."""

    task_id: str
    worker_objective: str
    error_type: str
    error_message: str
    metrics: TraceMetrics
    attempted_reasoning: list[str]


class TraceMetrics(BaseModel):
    """LLMOps metrics for the escalation trace."""

    ttft: float = Field(description="Time to first token (ms)")
    tps: float = Field(description="Tokens per second")
    cost: float = Field(description="Total USD cost across all attempts")


# ---------------------------------------------------------------------------
# Task execution log — full history
# ---------------------------------------------------------------------------


class TaskExecutionLog(BaseModel):
    """Complete execution history for a task, including all attempts."""

    task: ScientificTask
    attempts: list[AttemptRecord] = Field(default_factory=list)
    final_result: Optional[WorkerResult] = None
    escalation_payload: Optional[TracePayload] = None


# ---------------------------------------------------------------------------
# Fix forward references (FixerDiagnostics used before definition)
# ---------------------------------------------------------------------------

AttemptRecord.model_rebuild()
