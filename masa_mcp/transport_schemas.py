"""
Shared MCP transport schemas for MASA literature search tools.
"""

from __future__ import annotations

from enum import Enum
from typing import Annotated

from pydantic import BaseModel, ConfigDict, Field, field_validator


class EpistemicFilter(str, Enum):
    """Controls which publication types survive the epistemic wall."""

    ALL = "all"
    PEER_REVIEWED_ONLY = "peer_reviewed_only"


class _StrictModel(BaseModel):
    """Base schema that rejects unknown keys from MCP tool payloads."""

    model_config = ConfigDict(extra="forbid")


class LiteratureSearchArgs(_StrictModel):
    """Validated arguments for the literature_search tool."""

    query: Annotated[str, Field(strict=True)]
    epistemic_filter: EpistemicFilter = EpistemicFilter.PEER_REVIEWED_ONLY
    chunk_offset: Annotated[int, Field(default=0, ge=0, strict=True)]
    year_range: Annotated[str | None, Field(default=None, strict=True)]
    fields_of_study: list[Annotated[str, Field(strict=True)]] | None = None

    @field_validator("query")
    @classmethod
    def validate_query(cls, value: str) -> str:
        normalized = value.strip()
        if not normalized:
            raise ValueError("query must be a non-empty string")
        return normalized

    @field_validator("year_range")
    @classmethod
    def normalize_year_range(cls, value: str | None) -> str | None:
        if value is None:
            return None
        normalized = value.strip()
        return normalized or None

    @field_validator("fields_of_study")
    @classmethod
    def normalize_fields_of_study(cls, value: list[str] | None) -> list[str] | None:
        if value is None:
            return None
        normalized = [item.strip() for item in value if item.strip()]
        return normalized or None


class GetPaperDetailArgs(_StrictModel):
    """Validated arguments for the get_paper_detail tool."""

    paper_id: Annotated[str, Field(strict=True)]
    include_references: Annotated[bool, Field(default=False, strict=True)]

    @field_validator("paper_id")
    @classmethod
    def validate_paper_id(cls, value: str) -> str:
        normalized = value.strip()
        if not normalized:
            raise ValueError("paper_id must be a non-empty string")
        return normalized
