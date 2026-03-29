"""
MASA Orchestrator — Core Execution Loop
=========================================

The central engine that drives the Worker → Validate → Fix → Retry pipeline.

Flow per task:
  1. EXPLORATION attempt (temp=0.7, creative sampling)
  2. Parse raw JSON → Pydantic WorkerResult
  3. Run epistemic checks (reference ID verification, evidence consistency)
  4. On failure: invoke Fixer Agent, switch to FALLBACK config (temp=0.0, PRNG-locked)
  5. Retry with rewritten prompt (up to MAX_ATTEMPTS)
  6. On terminal failure: build TracePayload, escalate to Operator Console via SSE
"""

from __future__ import annotations

import json
import logging
import time
from typing import Optional

from pydantic import ValidationError

from clients.base import LLMClient, LLMResponse
from orchestrator.config import (
    EXPLORATION_CONFIG,
    MAX_ATTEMPTS,
    WORKER_MODEL,
    build_fallback_config,
)
from orchestrator.epistemic_checks import (
    EpistemicViolation,
    run_all_epistemic_checks,
)
from orchestrator.fixer import invoke_fixer
from orchestrator.models import (
    AttemptRecord,
    ExecutionConfig,
    ScientificTask,
    ServedReference,
    TaskExecutionLog,
    TaskStatus,
    TraceMetrics,
    TracePayload,
    WorkerResult,
)
from orchestrator.sse import SSEEmitter

logger = logging.getLogger("masa.orchestrator")


# ---------------------------------------------------------------------------
# Worker prompt construction
# ---------------------------------------------------------------------------


def build_worker_prompt(task: ScientificTask) -> str:
    """
    Build the initial Worker prompt from a ScientificTask.

    The prompt is structured to maximize schema compliance on the first attempt:
    - Explicit JSON schema constraints
    - Enumerated field requirements
    - Forbidden behaviors (no fabricated IDs, no hallucinated citations)
    """
    return f"""You are a MASA Scientific Worker agent.

Your task: {task.objective}

You MUST output STRICTLY valid JSON conforming to this schema:

{{
  "task_id": "{task.task_id}",
  "summary": "1-3 sentence summary of findings (10-2000 chars)",
  "evidence": [
    {{
      "reference_id": <int — MUST match a [Reference ID: N] from literature_search>,
      "claim": "<specific claim supported by this reference>",
      "strength": "<strong|moderate|weak>",
      "quote": "<optional direct quote from abstract>"
    }}
  ],
  "confidence": <float 0.0-1.0>,
  "reasoning_chain": ["step 1", "step 2", ...],
  "cited_reference_ids": [<int>, ...]
}}

CONSTRAINTS:
1. task_id MUST be exactly "{task.task_id}"
2. evidence MUST contain at least 1 item
3. Every reference_id MUST correspond to a [Reference ID: N] actually returned by literature_search
4. Every reference_id in evidence MUST also appear in cited_reference_ids
5. cited_reference_ids MUST be non-empty
6. confidence MUST be between 0.0 and 1.0
7. reasoning_chain MUST be non-empty
8. DO NOT fabricate reference IDs — only use IDs actually served to you
9. DO NOT include markdown, conversational filler, or text outside the JSON object

Output ONLY the JSON object. Nothing else."""


# ---------------------------------------------------------------------------
# Core execution loop
# ---------------------------------------------------------------------------


async def execute_task(
    task: ScientificTask,
    worker_client: LLMClient,
    fixer_client: LLMClient,
    served_references: dict[int, ServedReference],
    emitter: Optional[SSEEmitter] = None,
    worker_model: Optional[str] = None,
    fixer_model: Optional[str] = None,
) -> TaskExecutionLog:
    """
    Execute a ScientificTask through the full orchestration pipeline.

    This is the heart of the MASA Orchestrator. It drives:
      - Worker invocation with EXPLORATION → FALLBACK config escalation
      - Pydantic schema validation of Worker output
      - Epistemic boundary checks (reference ID verification)
      - Fixer Agent diagnosis and prompt rewriting on failure
      - PRNG seed locking for causal attribution on retries
      - 3-strike escalation to the Operator Console

    Args:
        task: The ScientificTask to execute.
        worker_client: LLM client for the Worker agent.
        fixer_client: LLM client for the Fixer agent.
        served_references: Authoritative ledger of [Reference ID: N] values actually
            returned by literature_search in this session.
        emitter: Optional SSE emitter for real-time console updates.
        worker_model: Optional model override for Worker.
        fixer_model: Optional model override for Fixer.

    Returns:
        TaskExecutionLog with the complete execution history.
    """
    _require_served_reference_context(task, served_references)

    w_model = worker_model or WORKER_MODEL
    max_attempts = task.max_attempts or MAX_ATTEMPTS

    log = TaskExecutionLog(task=task)
    current_prompt = build_worker_prompt(task)

    logger.info(
        "Starting execution: task=%s, max_attempts=%d, model=%s",
        task.task_id, max_attempts, w_model,
    )

    # Emit task started
    if emitter:
        await emitter.emit_task_status(task.task_id, TaskStatus.RUNNING)

    for attempt_num in range(1, max_attempts + 1):
        task.attempt_count = attempt_num
        is_first_attempt = attempt_num == 1

        # --- Select execution config ---
        if is_first_attempt:
            config = EXPLORATION_CONFIG
            mode = "EXPLORATION"
        else:
            config = build_fallback_config(task.task_id)
            mode = "FALLBACK"

        logger.info(
            "Attempt %d/%d [%s] — temp=%.1f, seed=%s",
            attempt_num, max_attempts, mode,
            config.temperature, config.seed,
        )

        # Emit attempt started
        if emitter:
            await emitter.emit_attempt_start(
                task.task_id, attempt_num, mode,
            )

        # --- Invoke Worker ---
        task.status = TaskStatus.RUNNING
        t0 = time.monotonic()

        try:
            response: LLMResponse = await worker_client.generate(
                prompt=current_prompt,
                temperature=config.temperature,
                top_p=config.top_p,
                top_k=config.top_k,
                seed=config.seed,
                response_format=config.response_format,
                model=w_model,
            )
        except Exception as exc:
            # LLM client failure — record and continue to next attempt
            elapsed = (time.monotonic() - t0) * 1000
            logger.error("Worker invocation failed: %s", exc)
            record = AttemptRecord(
                attempt_number=attempt_num,
                prompt_sent=current_prompt,
                raw_response="",
                validation_passed=False,
                error_trace=f"LLM client error: {exc}",
                error_type="ClientError",
                config_used=config,
                latency_ms=elapsed,
            )
            log.attempts.append(record)

            if emitter:
                await emitter.emit_attempt_result(
                    task.task_id, attempt_num, False,
                    error_type="ClientError",
                    error_msg=str(exc),
                )
            continue

        elapsed = (time.monotonic() - t0) * 1000

        logger.info(
            "Worker responded: %d tokens in %.0fms ($%.6f)",
            response.tokens_output, response.total_ms, response.cost_usd,
        )

        # --- Phase 1: JSON parse ---
        task.status = TaskStatus.VALIDATING

        try:
            raw_data = json.loads(response.text)
        except json.JSONDecodeError as exc:
            error_trace = f"JSON parse error: {exc}\nRaw output (first 500 chars): {response.text[:500]}"
            record = _build_attempt_record(
                attempt_num, current_prompt, response, config,
                elapsed, False, error_trace, "JSONParseError",
            )
            log.attempts.append(record)
            logger.warning("Attempt %d: JSON parse failed", attempt_num)

            if emitter:
                await emitter.emit_attempt_result(
                    task.task_id, attempt_num, False,
                    error_type="JSONParseError",
                    error_msg=str(exc),
                )

            # Invoke Fixer for rewrite
            current_prompt = await _run_fixer(
                fixer_client, task, error_trace,
                _extract_reasoning(raw_data=None),
                record, fixer_model,
            )
            continue

        # --- Phase 2: Pydantic validation ---
        try:
            result = WorkerResult.model_validate(raw_data)
        except ValidationError as exc:
            error_trace = f"Pydantic validation error:\n{exc}"
            record = _build_attempt_record(
                attempt_num, current_prompt, response, config,
                elapsed, False, error_trace, "PydanticValidationError",
            )
            log.attempts.append(record)
            logger.warning("Attempt %d: schema validation failed", attempt_num)

            if emitter:
                await emitter.emit_attempt_result(
                    task.task_id, attempt_num, False,
                    error_type="PydanticValidationError",
                    error_msg=str(exc)[:300],
                )

            current_prompt = await _run_fixer(
                fixer_client, task, error_trace,
                _extract_reasoning(raw_data),
                record, fixer_model,
            )
            continue

        # --- Phase 3: Epistemic checks ---
        try:
            run_all_epistemic_checks(result, task.task_id, served_references)
        except EpistemicViolation as exc:
            error_trace = f"Epistemic violation: {exc}"
            record = _build_attempt_record(
                attempt_num, current_prompt, response, config,
                elapsed, False, error_trace, "EpistemicBoundaryViolation",
            )
            log.attempts.append(record)
            logger.warning("Attempt %d: epistemic check failed — %s", attempt_num, exc)

            if emitter:
                await emitter.emit_attempt_result(
                    task.task_id, attempt_num, False,
                    error_type="EpistemicBoundaryViolation",
                    error_msg=str(exc),
                )

            current_prompt = await _run_fixer(
                fixer_client, task, error_trace,
                result.reasoning_chain,
                record, fixer_model,
            )
            continue

        # --- SUCCESS ---
        record = _build_attempt_record(
            attempt_num, current_prompt, response, config,
            elapsed, True, None, None,
        )
        log.attempts.append(record)
        log.final_result = result

        task.status = TaskStatus.SUCCEEDED
        logger.info(
            "Task %s SUCCEEDED on attempt %d (confidence=%.2f, %d citations)",
            task.task_id, attempt_num, result.confidence,
            len(result.cited_reference_ids),
        )

        if emitter:
            await emitter.emit_attempt_result(
                task.task_id, attempt_num, True,
            )
            await emitter.emit_task_status(task.task_id, TaskStatus.SUCCEEDED)

        return log

    # --- ESCALATION: all attempts exhausted ---
    task.status = TaskStatus.ESCALATED
    logger.warning(
        "Task %s ESCALATED after %d attempts", task.task_id, max_attempts,
    )

    escalation = _build_escalation_payload(task, log)
    log.escalation_payload = escalation

    if emitter:
        await emitter.emit_escalation(task.task_id, escalation)
        await emitter.emit_task_status(task.task_id, TaskStatus.ESCALATED)

    return log


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _build_attempt_record(
    attempt_number: int,
    prompt_sent: str,
    response: LLMResponse,
    config: ExecutionConfig,
    elapsed_ms: float,
    validation_passed: bool,
    error_trace: Optional[str],
    error_type: Optional[str],
) -> AttemptRecord:
    """Construct an immutable AttemptRecord from attempt data."""
    return AttemptRecord(
        attempt_number=attempt_number,
        prompt_sent=prompt_sent,
        raw_response=response.text,
        validation_passed=validation_passed,
        error_trace=error_trace,
        error_type=error_type,
        config_used=config,
        latency_ms=elapsed_ms,
        tokens_used=response.tokens_input + response.tokens_output,
        ttft_ms=response.ttft_ms,
        total_ms=response.total_ms,
        tokens_input=response.tokens_input,
        tokens_output=response.tokens_output,
        cost_usd=response.cost_usd,
    )


def _require_served_reference_context(
    task: ScientificTask,
    served_references: dict[int, ServedReference],
) -> None:
    """
    Refuse execution if the Worker depends on literature_search but no
    authoritative reference ledger has been established yet.
    """
    if "literature_search" not in task.required_tools:
        return
    if served_references:
        return
    raise ValueError(
        "Cannot execute task without an authoritative literature_search reference ledger. "
        "Ingest literature_search tool output before invoking the Worker."
    )


def _extract_reasoning(raw_data: Optional[dict]) -> list[str]:
    """
    Safely extract reasoning_chain from raw parsed data.

    If the data is unparseable or missing the field, return a placeholder
    so the Fixer still gets something to diagnose.
    """
    if raw_data is None:
        return ["[Worker output was not valid JSON — no reasoning available]"]

    chain = raw_data.get("reasoning_chain")
    if isinstance(chain, list) and chain:
        return [str(s) for s in chain]

    return ["[No reasoning_chain found in Worker output]"]


async def _run_fixer(
    fixer_client: LLMClient,
    task: ScientificTask,
    error_trace: str,
    attempted_reasoning: list[str],
    record: AttemptRecord,
    fixer_model: Optional[str],
) -> str:
    """
    Invoke the Fixer Agent and return the rewritten prompt.

    On Fixer failure, falls back to the original prompt with the error
    appended as a constraint — degraded but not dead.
    """
    task.status = TaskStatus.FIXING
    logger.info("Invoking Fixer Agent for task %s", task.task_id)

    try:
        fixer_output = await invoke_fixer(
            fixer_client=fixer_client,
            worker_objective=task.objective,
            error_trace=error_trace,
            attempted_reasoning=attempted_reasoning,
            model=fixer_model,
        )
        record.fixer_diagnostics = fixer_output.diagnostics
        record.rewritten_prompt = fixer_output.rewritten_prompt

        logger.info(
            "Fixer rewrite ready: failure_point=%s",
            fixer_output.diagnostics.failure_point[:80],
        )
        return fixer_output.rewritten_prompt

    except (ValueError, Exception) as exc:
        # Fixer itself failed — degrade gracefully
        logger.error("Fixer Agent failed: %s — using fallback prompt", exc)
        return (
            f"{build_worker_prompt(task)}\n\n"
            f"CRITICAL: Your previous attempt failed with this error:\n"
            f"{error_trace}\n\n"
            f"You MUST fix this exact issue in your response."
        )


def _build_escalation_payload(
    task: ScientificTask,
    log: TaskExecutionLog,
) -> TracePayload:
    """
    Build the TracePayload for Operator Console escalation.

    Aggregates metrics across all attempts and includes the last
    reasoning chain for operator review.
    """
    total_cost = sum(a.cost_usd for a in log.attempts)
    total_generation_ms = sum(a.total_ms for a in log.attempts)
    total_output_tokens = sum(a.tokens_output for a in log.attempts)

    # Compute average tokens per second across attempts
    if total_generation_ms > 0:
        tps = total_output_tokens / (total_generation_ms / 1000)
    else:
        tps = 0.0

    # Get the last error for the escalation message
    last_attempt = log.attempts[-1] if log.attempts else None
    error_type = last_attempt.error_type if last_attempt else "Unknown"
    error_message = last_attempt.error_trace if last_attempt else "No attempts recorded"

    # Extract reasoning from the last attempt's raw response
    last_reasoning = ["[No reasoning extracted]"]
    if last_attempt:
        try:
            raw = json.loads(last_attempt.raw_response)
            chain = raw.get("reasoning_chain", [])
            if isinstance(chain, list) and chain:
                last_reasoning = [str(s) for s in chain]
        except (json.JSONDecodeError, AttributeError):
            last_reasoning = ["[Could not parse reasoning from last attempt]"]

    return TracePayload(
        task_id=task.task_id,
        worker_objective=task.objective,
        error_type=error_type or "Unknown",
        error_message=error_message or "Terminal failure after all attempts",
        metrics=TraceMetrics(
            ttft=last_attempt.ttft_ms if last_attempt else 0.0,
            tps=tps,
            cost=total_cost,
        ),
        attempted_reasoning=last_reasoning,
    )
