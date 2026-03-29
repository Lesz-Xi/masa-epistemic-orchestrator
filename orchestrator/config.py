"""
MASA Orchestrator — Execution Configuration & PRNG Seed Generation
===================================================================

Two execution states: EXPLORATION (creative) and FALLBACK (deterministic).
The seed is derived from the task_id via SHA-256 so retries are reproducible.
"""

from __future__ import annotations

import hashlib
import os

from orchestrator.models import ExecutionConfig

_SEED_MAX = (2**31) - 1

# ---------------------------------------------------------------------------
# Execution state configurations
# ---------------------------------------------------------------------------

EXPLORATION_CONFIG = ExecutionConfig(
    temperature=0.7,
    top_p=0.9,
    top_k=40,
)

FALLBACK_CONFIG_TEMPLATE = ExecutionConfig(
    temperature=0.0,
    top_p=0.1,
    top_k=1,
)

# ---------------------------------------------------------------------------
# PRNG seed derivation
# ---------------------------------------------------------------------------


def generate_deterministic_seed(task_id: str) -> int:
    """
    Derive a consistent integer seed from a task ID.

    Same task_id always produces the same seed, enabling causal attribution:
    if the Worker's output changes between retries, it was caused by the
    rewritten prompt — not random sampling.
    """
    hash_obj = hashlib.sha256(task_id.encode("utf-8"))
    return int(hash_obj.hexdigest()[:8], 16) % _SEED_MAX


def build_fallback_config(task_id: str) -> ExecutionConfig:
    """Build a FALLBACK config with the deterministic seed locked to this task."""
    return ExecutionConfig(
        temperature=FALLBACK_CONFIG_TEMPLATE.temperature,
        top_p=FALLBACK_CONFIG_TEMPLATE.top_p,
        top_k=FALLBACK_CONFIG_TEMPLATE.top_k,
        seed=generate_deterministic_seed(task_id),
    )


# ---------------------------------------------------------------------------
# Runtime settings
# ---------------------------------------------------------------------------

MAX_ATTEMPTS: int = int(os.getenv("MASA_MAX_ATTEMPTS", "3"))
WORKER_MODEL: str = os.getenv("MASA_WORKER_MODEL", "claude-sonnet-4-20250514")
FIXER_MODEL: str = os.getenv("MASA_FIXER_MODEL", "gemini-2.0-flash")
SSE_PORT: int = int(os.getenv("MASA_SSE_PORT", "3201"))
