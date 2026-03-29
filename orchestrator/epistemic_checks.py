"""
MASA Orchestrator — Epistemic Checks
======================================

Post-schema validation guardrails that enforce the epistemic wall.
These catch cases where the Worker's output is valid JSON/Pydantic
but violates deeper scientific integrity constraints.
"""

from __future__ import annotations

import logging

from orchestrator.models import ServedReference, WorkerResult

logger = logging.getLogger("masa.epistemic")


class EpistemicViolation(Exception):
    """
    Raised when Worker output passes schema validation but violates
    an epistemic constraint.

    This is distinct from PydanticValidationError — it means the structure
    is correct but the content is epistemically unsound.
    """

    pass


def verify_reference_ids_exist(
    result: WorkerResult,
    served_references: dict[int, ServedReference],
) -> None:
    """
    Every reference_id in cited_reference_ids must correspond to a paper
    that was actually returned by literature_search in this session.

    Prevents the Worker from fabricating reference IDs — the most common
    form of LLM hallucination in citation-heavy tasks.

    Args:
        result: The validated WorkerResult.
        served_references: Authoritative ledger of [Reference ID: N] values actually
            returned by the MCP server during this task's execution.

    Raises:
        EpistemicViolation: If any cited reference was never served.
    """
    if not served_references:
        raise EpistemicViolation(
            "No served reference ledger available; refusing citation validation."
        )

    cited = set(result.cited_reference_ids)
    served_reference_ids = set(served_references)
    fabricated = cited - served_reference_ids

    if fabricated:
        # Also check evidence items
        evidence_refs = {e.reference_id for e in result.evidence}
        all_fabricated = fabricated | (evidence_refs - served_reference_ids)

        raise EpistemicViolation(
            f"Worker cited reference IDs {sorted(all_fabricated)} that were never "
            f"returned by literature_search. "
            f"Served IDs: {sorted(served_reference_ids)}. "
            f"This is a hallucinated citation and must be corrected."
        )


def verify_evidence_references_cited(result: WorkerResult) -> None:
    """
    Every reference_id in evidence items must also appear in cited_reference_ids.

    Catches inconsistencies where the Worker lists evidence from a reference
    but forgets to include it in the citation list.

    Raises:
        EpistemicViolation: If evidence references are not in the citation list.
    """
    cited_set = set(result.cited_reference_ids)
    evidence_refs = {e.reference_id for e in result.evidence}
    uncited = evidence_refs - cited_set

    if uncited:
        raise EpistemicViolation(
            f"Evidence items reference IDs {sorted(uncited)} that are not in "
            f"cited_reference_ids {sorted(cited_set)}. "
            f"All evidence references must be explicitly cited."
        )


def verify_task_id_match(result: WorkerResult, expected_task_id: str) -> None:
    """
    The task_id in the Worker's output must match the assigned task.

    Catches cases where the Worker confuses task contexts (possible in
    multi-task pipelines or cached prompts).

    Raises:
        EpistemicViolation: If task IDs don't match.
    """
    if result.task_id != expected_task_id:
        raise EpistemicViolation(
            f"Worker output task_id '{result.task_id}' does not match "
            f"assigned task '{expected_task_id}'. "
            f"Possible context confusion between tasks."
        )


def run_all_epistemic_checks(
    result: WorkerResult,
    expected_task_id: str,
    served_references: dict[int, ServedReference],
) -> None:
    """
    Run the full epistemic check suite.

    Raises the first EpistemicViolation encountered.
    """
    verify_task_id_match(result, expected_task_id)
    verify_reference_ids_exist(result, served_references)
    verify_evidence_references_cited(result)

    logger.info("All epistemic checks passed for task %s", expected_task_id)
