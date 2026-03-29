"""
MASA LLM Client — Abstract Interface
======================================

Provider-agnostic interface for calling LLMs.
Concrete implementations: AnthropicClient (Worker), GoogleClient (Fixer), MockClient (tests).
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Optional

from pydantic import BaseModel, Field


class LLMResponse(BaseModel):
    """Structured response from any LLM provider."""

    text: str = Field(description="Raw text output from the model")
    model: str = Field(description="Model identifier used")
    tokens_input: int = Field(default=0, description="Input token count")
    tokens_output: int = Field(default=0, description="Output token count")
    cost_usd: float = Field(default=0.0, description="Estimated cost in USD")
    ttft_ms: float = Field(default=0.0, description="Time to first token (ms)")
    total_ms: float = Field(default=0.0, description="Total generation time (ms)")


class LLMClient(ABC):
    """
    Abstract LLM client interface.

    All orchestrator code programs against this interface.
    Swap implementations for testing (MockClient) vs production
    (AnthropicClient, GoogleClient).
    """

    @abstractmethod
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
        """
        Generate a completion from the LLM.

        Args:
            prompt: The full prompt to send.
            temperature: Sampling temperature.
            top_p: Nucleus sampling threshold.
            top_k: Top-k token pool.
            seed: Optional deterministic seed (for PRNG locking).
            response_format: Optional format constraint (e.g., {"type": "json_object"}).
            model: Optional model override.

        Returns:
            LLMResponse with the raw text and usage metrics.
        """
        ...
