"""
MASA Orchestrator — Served reference ledger parsing.

Parses server-owned literature_search responses into an authoritative
reference ledger for downstream citation validation.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from orchestrator.models import ServedReference

_REFERENCE_HEADER_RE = re.compile(r"^\[Reference ID: (?P<ref_id>\d+)\]$")
_TITLE_RE = re.compile(r"^\s*Title:\s*(?P<title>.+?)\s*$")
_PAPER_ID_RE = re.compile(r"^\s*Semantic Scholar ID:\s*(?P<paper_id>.+?)\s*$")


def parse_literature_search_response(response_text: str) -> dict[int, ServedReference]:
    """
    Extract served references from a literature_search response.

    Only server-owned `literature_search` output is supported. The parser
    requires a `Semantic Scholar ID:` line for each reference block so the
    ledger is tied to stable upstream paper identifiers.
    """
    ledger = ServedReferenceLedger()
    ledger.ingest("literature_search", response_text)
    return ledger.snapshot()


@dataclass
class ServedReferenceLedger:
    """Mutable collector for served literature references across tool calls."""

    _entries: dict[int, ServedReference] = field(default_factory=dict)

    def ingest(self, tool_name: str, response_text: str) -> None:
        """
        Parse a tool response and merge any served literature references.

        Verification-only tools intentionally do not mint citable references.
        Unknown tools are ignored so callers can safely pass mixed tool traces.
        """
        if tool_name != "literature_search":
            return

        pending_ref_id: int | None = None
        pending_title: str | None = None

        for raw_line in response_text.splitlines():
            line = raw_line.rstrip()

            header_match = _REFERENCE_HEADER_RE.match(line)
            if header_match:
                pending_ref_id = int(header_match.group("ref_id"))
                pending_title = None
                continue

            if pending_ref_id is None:
                continue

            title_match = _TITLE_RE.match(line)
            if title_match:
                pending_title = title_match.group("title")
                continue

            paper_id_match = _PAPER_ID_RE.match(line)
            if paper_id_match:
                paper_id = paper_id_match.group("paper_id").strip()
                if not paper_id:
                    raise ValueError(f"Reference {pending_ref_id} is missing a Semantic Scholar ID.")
                self._record(
                    ServedReference(
                        ref_id=pending_ref_id,
                        paper_id=paper_id,
                        title=pending_title,
                    )
                )
                pending_ref_id = None
                pending_title = None

        if pending_ref_id is not None:
            raise ValueError(
                f"Reference {pending_ref_id} is incomplete; missing Semantic Scholar ID in tool output."
            )

    def snapshot(self) -> dict[int, ServedReference]:
        """Return a shallow copy of the authoritative served-reference ledger."""
        return dict(self._entries)

    def _record(self, reference: ServedReference) -> None:
        existing = self._entries.get(reference.ref_id)
        if existing is None:
            self._entries[reference.ref_id] = reference
            return
        if existing.paper_id != reference.paper_id:
            raise ValueError(
                f"Reference ID collision for {reference.ref_id}: "
                f"{existing.paper_id!r} != {reference.paper_id!r}"
            )
