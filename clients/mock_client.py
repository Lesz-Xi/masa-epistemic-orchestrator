"""
MASA LLM Client — Deterministic Mock
======================================

Returns pre-configured responses for testing the orchestration loop
without hitting real APIs.
"""

from __future__ import annotations

import json
import time
from typing import Optional

from clients.base import LLMClient, LLMResponse


class MockClient(LLMClient):
    """
    Deterministic mock LLM client.

    Responses are queued via `enqueue()`. Each call to `generate()` pops
    the next response from the queue. If the queue is empty, returns a
    fallback error response.
    """

    def __init__(self, model_name: str = "mock-model") -> None:
        self._model_name = model_name
        self._queue: list[str] = []
        self._call_log: list[dict] = []

    def enqueue(self, *responses: str) -> None:
        """Add one or more raw text responses to the queue."""
        self._queue.extend(responses)

    def enqueue_json(self, *objects: dict) -> None:
        """Add one or more JSON-serializable objects to the queue."""
        for obj in objects:
            self._queue.append(json.dumps(obj))

    @property
    def call_count(self) -> int:
        return len(self._call_log)

    @property
    def last_call(self) -> dict | None:
        return self._call_log[-1] if self._call_log else None

    async def generate(
        self,
        prompt: str,
        *,
        temperature: float = 0.7,
        top_p: float = 0.9,
        top_k: int = 40,
        seed: Optional[int] = None,
        response_format: Optional[dict[str, str]] = None,
        model: Optional[str] = None,
    ) -> LLMResponse:
        # Record the call for assertions
        self._call_log.append({
            "prompt": prompt,
            "temperature": temperature,
            "top_p": top_p,
            "top_k": top_k,
            "seed": seed,
            "response_format": response_format,
            "model": model,
            "timestamp": time.time(),
        })

        if self._queue:
            text = self._queue.pop(0)
        else:
            text = json.dumps({
                "error": "MockClient queue exhausted — no response configured for this call"
            })

        # Simulate realistic-ish metrics
        token_estimate = len(text.split()) * 2
        return LLMResponse(
            text=text,
            model=model or self._model_name,
            tokens_input=len(prompt.split()) * 2,
            tokens_output=token_estimate,
            cost_usd=token_estimate * 0.000003,  # ~$3/M output tokens
            ttft_ms=50.0,
            total_ms=200.0,
        )
