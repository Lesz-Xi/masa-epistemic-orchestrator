"""
MASA Orchestrator — Literature Search MCP Server
=================================================

Production-grade MCP tool server implementing the Epistemic Wall architecture.

Core guarantees:
  1. Epistemic Filter  — server-side enforcement of peer_reviewed_only; pre-prints
     are physically stripped before the payload reaches the LLM Worker.
  2. Context Window Protection — strict chunk_offset pagination; the server never
     returns more than CHUNK_SIZE papers per call.
  3. Reference ID Injection — every paper gets a synthetic [Reference ID: N] that
     the Worker must cite downstream.
  4. Robust Error Semantics — rate-limit, zero-result, and transport errors return
     structured diagnostic strings so the Fixer Agent can auto-correct the query.

Backend: Semantic Scholar Academic Graph API (free, no key required for basic use).
Transport: stdio (default) or streamable-http via MCP SDK.
"""

from __future__ import annotations

import asyncio
import copy
import hashlib
import logging
import os
import sys
import time
from dataclasses import dataclass, field
from typing import Any, Optional

import httpx
from mcp.server import Server
from mcp.server.stdio import stdio_server
from mcp.types import TextContent, Tool
from pydantic import ValidationError

from masa_mcp.transport_schemas import EpistemicFilter, GetPaperDetailArgs, LiteratureSearchArgs

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

SERVER_VERSION: str = "2.1.0"
"""Server version string reported by health_check."""

CHUNK_SIZE: int = int(os.getenv("MASA_CHUNK_SIZE", "3"))
"""Max papers returned per invocation.  Protects the Worker's context window."""

SEMANTIC_SCHOLAR_BASE: str = "https://api.semanticscholar.org/graph/v1"
SEMANTIC_SCHOLAR_KEY: str | None = os.getenv("SEMANTIC_SCHOLAR_API_KEY")
"""Optional.  If set, sent as x-api-key header for higher rate limits."""

REQUEST_TIMEOUT: float = float(os.getenv("MASA_REQUEST_TIMEOUT", "30"))
"""Seconds before we abandon a Semantic Scholar request."""

MAX_TOTAL_RESULTS: int = int(os.getenv("MASA_MAX_TOTAL_RESULTS", "100"))
"""Upper bound on how many papers we ask the upstream API for."""

LOG_LEVEL: str = os.getenv("MASA_LOG_LEVEL", "INFO").upper()

# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------

logging.basicConfig(
    level=getattr(logging, LOG_LEVEL, logging.INFO),
    format="%(asctime)s [%(levelname)s] %(name)s — %(message)s",
    stream=sys.stderr,
)
logger = logging.getLogger("masa.literature_search")

@dataclass(frozen=True)
class Paper:
    """Normalized representation of a single search result."""

    paper_id: str
    title: str
    abstract: str
    authors: list[str]
    year: int | None
    venue: str
    citation_count: int
    is_open_access: bool
    url: str
    publication_types: list[str]

    @property
    def is_preprint(self) -> bool:
        """
        Heuristic: a paper is a pre-print if Semantic Scholar marks it as such
        OR it has no venue and no journal publication type.
        """
        lowered = [t.lower() for t in self.publication_types]
        if "preprint" in lowered:
            return True
        if not self.venue and "journalarticle" not in lowered and "conference" not in lowered:
            return True
        return False


@dataclass
class SearchResult:
    """Full result set before pagination / filtering."""

    papers: list[Paper] = field(default_factory=list)
    total_upstream: int = 0
    query: str = ""
    elapsed_ms: float = 0.0


# ---------------------------------------------------------------------------
# Result Cache — LRU with TTL (pre-filter keying)
# ---------------------------------------------------------------------------


@dataclass
class CacheEntry:
    """A cached search result with timestamp for TTL enforcement."""

    result: SearchResult
    timestamp: float  # time.monotonic()
    last_accessed: float  # for LRU ordering


class ResultCache:
    """
    LRU cache for Semantic Scholar queries.

    Keyed by (query, year_range, frozenset(fields_of_study)).
    Cache is PRE-filter: epistemic filtering runs after cache retrieval,
    so a cached 'all' result can serve a subsequent 'peer_reviewed_only'
    request without re-hitting the API.
    """

    TTL: float = 300.0  # 5 minutes
    MAX_ENTRIES: int = 50

    def __init__(self, *, ttl: float | None = None, max_entries: int | None = None) -> None:
        self._store: dict[tuple, CacheEntry] = {}
        if ttl is not None:
            self.TTL = ttl
        if max_entries is not None:
            self.MAX_ENTRIES = max_entries

    @staticmethod
    def make_key(
        query: str,
        year_range: str | None,
        fields_of_study: list[str] | None,
    ) -> tuple:
        """Build a hashable cache key from search parameters."""
        fos = frozenset(sorted(fields_of_study)) if fields_of_study else frozenset()
        return (query.strip().lower(), year_range or "", fos)

    def get(self, key: tuple) -> SearchResult | None:
        """Return cached result if present and not expired, else None."""
        entry = self._store.get(key)
        if entry is None:
            return None

        now = time.monotonic()
        if now - entry.timestamp > self.TTL:
            # Expired — evict and return miss
            del self._store[key]
            logger.debug("Cache expired for key=%s", key[:2])
            return None

        # Update LRU timestamp
        entry.last_accessed = now
        logger.debug("Cache HIT for key=%s", key[:2])

        # Return a deep copy so callers can mutate papers list (epistemic filter)
        return copy.deepcopy(entry.result)

    def put(self, key: tuple, result: SearchResult) -> None:
        """Store a result, evicting the oldest entry if at capacity."""
        now = time.monotonic()

        # Evict least-recently-accessed if at capacity
        if len(self._store) >= self.MAX_ENTRIES and key not in self._store:
            oldest_key = min(self._store, key=lambda k: self._store[k].last_accessed)
            del self._store[oldest_key]
            logger.debug("Cache evicted oldest entry: key=%s", oldest_key[:2])

        self._store[key] = CacheEntry(
            result=copy.deepcopy(result),
            timestamp=now,
            last_accessed=now,
        )
        logger.debug("Cache PUT for key=%s (store_size=%d)", key[:2], len(self._store))

    def invalidate_all(self) -> None:
        """Clear the entire cache."""
        self._store.clear()
        logger.info("Cache invalidated (all entries cleared)")

    @property
    def size(self) -> int:
        """Current number of entries in the cache."""
        return len(self._store)


# ---------------------------------------------------------------------------
# Semantic Scholar client
# ---------------------------------------------------------------------------


class SemanticScholarClient:
    """Thin async wrapper around the Semantic Scholar Academic Graph API."""

    SEARCH_FIELDS: str = (
        "paperId,title,abstract,authors,year,venue,"
        "citationCount,isOpenAccess,url,publicationTypes"
    )

    PAPER_FIELDS: str = (
        "paperId,title,abstract,authors,year,venue,"
        "citationCount,isOpenAccess,url,publicationTypes"
    )

    PAPER_FIELDS_WITH_REFS: str = (
        "paperId,title,abstract,authors,year,venue,"
        "citationCount,isOpenAccess,url,publicationTypes,"
        "references.paperId,references.title,references.year,references.authors"
    )

    def __init__(self) -> None:
        headers: dict[str, str] = {"Accept": "application/json"}
        if SEMANTIC_SCHOLAR_KEY:
            headers["x-api-key"] = SEMANTIC_SCHOLAR_KEY
        self._client = httpx.AsyncClient(
            base_url=SEMANTIC_SCHOLAR_BASE,
            headers=headers,
            timeout=httpx.Timeout(REQUEST_TIMEOUT),
        )

    async def search(
        self,
        query: str,
        *,
        limit: int = MAX_TOTAL_RESULTS,
        year_range: str | None = None,
        fields_of_study: list[str] | None = None,
    ) -> SearchResult:
        """
        Execute a relevance-ranked paper search.

        Returns a SearchResult containing *all* upstream hits (up to `limit`).
        Filtering and pagination happen in the tool layer, not here.
        """
        params: dict[str, Any] = {
            "query": query,
            "limit": min(limit, MAX_TOTAL_RESULTS),
            "fields": self.SEARCH_FIELDS,
        }
        if year_range:
            params["year"] = year_range
        if fields_of_study:
            params["fieldsOfStudy"] = ",".join(fields_of_study)

        t0 = time.monotonic()
        try:
            resp = await self._client.get("/paper/search", params=params)
        except httpx.TimeoutException:
            raise UpstreamTimeout(query)
        except httpx.ConnectError as exc:
            raise UpstreamConnectionError(query, str(exc))

        elapsed = (time.monotonic() - t0) * 1000

        if resp.status_code == 429:
            raise RateLimited(query)
        if resp.status_code >= 500:
            raise UpstreamServerError(query, resp.status_code)
        resp.raise_for_status()

        body = resp.json()
        raw_papers: list[dict[str, Any]] = body.get("data", [])

        papers: list[Paper] = []
        for raw in raw_papers:
            authors = [a.get("name", "Unknown") for a in (raw.get("authors") or [])]
            papers.append(
                Paper(
                    paper_id=raw.get("paperId", ""),
                    title=raw.get("title", "Untitled"),
                    abstract=raw.get("abstract") or "(No abstract available)",
                    authors=authors,
                    year=raw.get("year"),
                    venue=raw.get("venue") or "",
                    citation_count=raw.get("citationCount", 0),
                    is_open_access=raw.get("isOpenAccess", False),
                    url=raw.get("url") or f"https://api.semanticscholar.org/{raw.get('paperId', '')}",
                    publication_types=raw.get("publicationTypes") or [],
                )
            )

        return SearchResult(
            papers=papers,
            total_upstream=body.get("total", len(papers)),
            query=query,
            elapsed_ms=elapsed,
        )

    async def get_paper(
        self,
        paper_id: str,
        *,
        include_references: bool = False,
    ) -> tuple[Paper, list[dict[str, Any]]]:
        """
        Fetch a single paper by its Semantic Scholar ID.

        Returns:
            (paper, references) where references is a list of dicts
            with paperId/title/year/authors if include_references=True,
            otherwise an empty list.
        """
        fields = self.PAPER_FIELDS_WITH_REFS if include_references else self.PAPER_FIELDS

        t0 = time.monotonic()
        try:
            resp = await self._client.get(f"/paper/{paper_id}", params={"fields": fields})
        except httpx.TimeoutException:
            raise UpstreamTimeout(paper_id)
        except httpx.ConnectError as exc:
            raise UpstreamConnectionError(paper_id, str(exc))

        elapsed = (time.monotonic() - t0) * 1000

        if resp.status_code == 404:
            raise PaperNotFound(paper_id)
        if resp.status_code == 429:
            raise RateLimited(paper_id)
        if resp.status_code >= 500:
            raise UpstreamServerError(paper_id, resp.status_code)
        resp.raise_for_status()

        raw = resp.json()
        authors = [a.get("name", "Unknown") for a in (raw.get("authors") or [])]

        paper = Paper(
            paper_id=raw.get("paperId", ""),
            title=raw.get("title", "Untitled"),
            abstract=raw.get("abstract") or "(No abstract available)",
            authors=authors,
            year=raw.get("year"),
            venue=raw.get("venue") or "",
            citation_count=raw.get("citationCount", 0),
            is_open_access=raw.get("isOpenAccess", False),
            url=raw.get("url") or f"https://api.semanticscholar.org/{raw.get('paperId', '')}",
            publication_types=raw.get("publicationTypes") or [],
        )

        references: list[dict[str, Any]] = []
        if include_references:
            for ref in (raw.get("references") or []):
                if ref and ref.get("paperId"):
                    ref_authors = [a.get("name", "Unknown") for a in (ref.get("authors") or [])]
                    references.append({
                        "paperId": ref["paperId"],
                        "title": ref.get("title", "Untitled"),
                        "year": ref.get("year"),
                        "authors": ref_authors,
                    })

        return paper, references

    async def ping(self) -> tuple[bool, float]:
        """
        Ping the Semantic Scholar API to check reachability.

        Returns:
            (reachable, latency_ms)
        """
        t0 = time.monotonic()
        try:
            resp = await self._client.get(
                "/paper/search",
                params={"query": "test", "limit": 1, "fields": "paperId"},
            )
            elapsed = (time.monotonic() - t0) * 1000
            return resp.status_code < 500, elapsed
        except (httpx.TimeoutException, httpx.ConnectError):
            elapsed = (time.monotonic() - t0) * 1000
            return False, elapsed

    async def close(self) -> None:
        await self._client.aclose()


# ---------------------------------------------------------------------------
# Structured error hierarchy — every error becomes a clean LLM-readable string
# ---------------------------------------------------------------------------


class LiteratureSearchError(Exception):
    """Base for all recoverable search errors."""

    def to_tool_response(self) -> str:
        raise NotImplementedError


class RateLimited(LiteratureSearchError):
    def __init__(self, query: str) -> None:
        self.query = query

    def to_tool_response(self) -> str:
        return (
            "[RATE_LIMITED] The upstream academic API has throttled this request.\n"
            f"Query: \"{self.query}\"\n"
            "Action: Wait 30–60 seconds and retry with the same parameters, "
            "or reduce the query specificity to lower API load.\n"
            "Do NOT change the epistemic_filter or chunk_offset — this is a transient error."
        )


class UpstreamTimeout(LiteratureSearchError):
    def __init__(self, query: str) -> None:
        self.query = query

    def to_tool_response(self) -> str:
        return (
            f"[TIMEOUT] The upstream API did not respond within {REQUEST_TIMEOUT}s.\n"
            f"Query: \"{self.query}\"\n"
            "Action: Retry with a simpler or shorter query string.  "
            "If this persists, the Semantic Scholar API may be experiencing an outage."
        )


class UpstreamConnectionError(LiteratureSearchError):
    def __init__(self, query: str, detail: str) -> None:
        self.query = query
        self.detail = detail

    def to_tool_response(self) -> str:
        return (
            "[CONNECTION_ERROR] Could not reach the upstream academic API.\n"
            f"Query: \"{self.query}\"\n"
            f"Detail: {self.detail}\n"
            "Action: This is a network-level failure.  Retry after 60 seconds."
        )


class UpstreamServerError(LiteratureSearchError):
    def __init__(self, query: str, status: int) -> None:
        self.query = query
        self.status = status

    def to_tool_response(self) -> str:
        return (
            f"[UPSTREAM_ERROR] Semantic Scholar returned HTTP {self.status}.\n"
            f"Query: \"{self.query}\"\n"
            "Action: This is a server-side error.  Retry after 60 seconds.  "
            "If it persists, try an alternative query formulation."
        )


class PaperNotFound(LiteratureSearchError):
    """Raised when a paper ID lookup returns 404."""

    def __init__(self, paper_id: str) -> None:
        self.paper_id = paper_id

    def to_tool_response(self) -> str:
        return (
            f"[PAPER_NOT_FOUND] No paper exists with ID '{self.paper_id}'.\n"
            "Action: Verify the Semantic Scholar paper ID.  It may have been "
            "removed from the index, or the ID format may be incorrect.\n"
            "Valid formats: 40-character hex hash, DOI, ArXiv ID, or URL."
        )


class ZeroResults(LiteratureSearchError):
    def __init__(self, query: str, epistemic_filter: str, had_preprints: int = 0) -> None:
        self.query = query
        self.epistemic_filter = epistemic_filter
        self.had_preprints = had_preprints

    def to_tool_response(self) -> str:
        lines = [
            "[ZERO_RESULTS] No papers matched the search criteria.",
            f"Query: \"{self.query}\"",
            f"Epistemic Filter: {self.epistemic_filter}",
        ]
        if self.had_preprints > 0:
            lines.append(
                f"Note: {self.had_preprints} pre-print(s) were found but excluded "
                "by the peer_reviewed_only filter."
            )
            lines.append(
                "Action: If pre-prints are acceptable for this task, retry with "
                'epistemic_filter="all".  Otherwise, broaden or rephrase the query.'
            )
        else:
            lines.append(
                "Action: Broaden the query terms, remove year constraints, "
                "or try synonyms.  The Semantic Scholar index may not cover "
                "this exact phrasing."
            )
        return "\n".join(lines)


# ---------------------------------------------------------------------------
# Output formatter — the Reference ID contract
# ---------------------------------------------------------------------------


def format_paper_block(paper: Paper, ref_id: int) -> str:
    """
    Format a single paper as a structured, LLM-readable text block.

    The [Reference ID: N] prefix is the citation anchor the Worker MUST use
    in downstream outputs.
    """
    authors_str = ", ".join(paper.authors[:5])
    if len(paper.authors) > 5:
        authors_str += f" … (+{len(paper.authors) - 5} more)"

    year_str = str(paper.year) if paper.year else "n.d."
    oa_badge = " [Open Access]" if paper.is_open_access else ""
    venue_str = f"  Venue: {paper.venue}\n" if paper.venue else ""

    return (
        f"[Reference ID: {ref_id}]\n"
        f"  Title: {paper.title}\n"
        f"  Authors: {authors_str}\n"
        f"  Year: {year_str}{oa_badge}\n"
        f"{venue_str}"
        f"  Citations: {paper.citation_count}\n"
        f"  Semantic Scholar ID: {paper.paper_id}\n"
        f"  URL: {paper.url}\n"
        f"  Abstract: {paper.abstract}\n"
    )


def format_paper_detail_response(
    paper: Paper,
    references: list[dict[str, Any]],
    elapsed_ms: float,
) -> str:
    """Format a single-paper detail response with optional reference list."""
    authors_str = ", ".join(paper.authors[:5])
    if len(paper.authors) > 5:
        authors_str += f" … (+{len(paper.authors) - 5} more)"

    year_str = str(paper.year) if paper.year else "n.d."
    oa_badge = " [Open Access]" if paper.is_open_access else ""
    lines: list[str] = []

    lines.append("=" * 60)
    lines.append("MASA Literature Search — Paper Detail")
    lines.append("=" * 60)
    lines.append(f"API Latency: {elapsed_ms:.0f} ms")
    lines.append("-" * 60)
    lines.append(f"Title: {paper.title}")
    lines.append(f"Authors: {authors_str}")
    lines.append(f"Year: {year_str}{oa_badge}")
    lines.append(f"Venue: {paper.venue or 'Unknown'}")
    lines.append(f"Citations: {paper.citation_count}")
    lines.append(f"Semantic Scholar ID: {paper.paper_id}")
    lines.append(f"URL: {paper.url}")
    lines.append(f"Abstract: {paper.abstract}")

    if references:
        lines.append("=" * 60)
        lines.append(f"REFERENCE LIST ({len(references)} outgoing citations)")
        lines.append("=" * 60)
        for i, ref in enumerate(references, start=1):
            ref_authors = ", ".join(ref.get("authors", [])[:3])
            if len(ref.get("authors", [])) > 3:
                ref_authors += " et al."
            year_str = str(ref.get("year", "n.d.")) if ref.get("year") else "n.d."
            lines.append(
                f"  [{i}] {ref.get('title', 'Untitled')} "
                f"({year_str}) — {ref_authors} "
                f"[S2ID: {ref.get('paperId', 'unknown')}]"
            )

    lines.append("")
    lines.append(
        "VERIFICATION ONLY: This tool does not mint citable [Reference ID: N] values. "
        "Use it to verify metadata for an existing paper, not to introduce new citations."
    )

    return "\n".join(lines)


def format_search_response(
    papers: list[Paper],
    *,
    chunk_offset: int,
    total_after_filter: int,
    total_upstream: int,
    query: str,
    epistemic_filter: str,
    elapsed_ms: float,
    preprints_removed: int,
    cache_hit: bool = False,
) -> str:
    """
    Compose the full tool response string including pagination metadata.
    """
    chunk_end = chunk_offset + len(papers)
    lines: list[str] = []

    # Header
    lines.append("=" * 60)
    lines.append("MASA Literature Search — Results")
    lines.append("=" * 60)
    lines.append(f"Query: \"{query}\"")
    lines.append(f"Epistemic Filter: {epistemic_filter}")
    lines.append(f"Upstream Hits: {total_upstream}")
    if preprints_removed > 0:
        lines.append(f"Pre-prints Removed (server-side): {preprints_removed}")
    lines.append(f"Eligible Papers (post-filter): {total_after_filter}")
    lines.append(f"Showing: {chunk_offset + 1}–{chunk_end} of {total_after_filter}")
    if cache_hit:
        lines.append("Source: cached (no API call)")
    else:
        lines.append(f"API Latency: {elapsed_ms:.0f} ms")
    lines.append("-" * 60)

    # Paper blocks
    for i, paper in enumerate(papers):
        ref_id = chunk_offset + i + 1  # 1-indexed
        lines.append(format_paper_block(paper, ref_id))
        lines.append("-" * 40)

    # Pagination hint
    if chunk_end < total_after_filter:
        remaining = total_after_filter - chunk_end
        lines.append(
            f"[PAGINATION] {remaining} more paper(s) available.  "
            f"To see the next page, call this tool again with chunk_offset={chunk_end}."
        )
    else:
        lines.append("[END OF RESULTS] All matching papers have been returned.")

    # Citation contract
    lines.append("")
    lines.append(
        "CITATION CONTRACT: You MUST cite papers using their [Reference ID: N] "
        "in any downstream output.  Do not fabricate references."
    )

    return "\n".join(lines)


# ---------------------------------------------------------------------------
# MCP Server definition
# ---------------------------------------------------------------------------

LITERATURE_SEARCH_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "query": {
            "type": "string",
            "description": (
                "Natural-language search query for academic papers.  "
                "Use specific scientific terms for best results."
            ),
        },
        "epistemic_filter": {
            "type": "string",
            "enum": ["all", "peer_reviewed_only"],
            "default": "peer_reviewed_only",
            "description": (
                "Controls the epistemic boundary.  "
                "'peer_reviewed_only' (default) physically removes pre-prints "
                "from the result set on the server before returning.  "
                "'all' includes pre-prints."
            ),
        },
        "chunk_offset": {
            "type": "integer",
            "default": 0,
            "minimum": 0,
            "description": (
                "Pagination cursor.  Start at 0.  The server returns at most "
                f"{CHUNK_SIZE} papers per call.  Use the offset returned in the "
                "pagination hint to fetch subsequent pages."
            ),
        },
        "year_range": {
            "type": "string",
            "description": (
                "Optional year filter.  Examples: '2020-2025', '2023-', '-2020'.  "
                "Maps to Semantic Scholar year parameter."
            ),
        },
        "fields_of_study": {
            "type": "array",
            "items": {"type": "string"},
            "description": (
                "Optional discipline filter.  Valid values include: "
                "'Computer Science', 'Medicine', 'Biology', 'Physics', "
                "'Chemistry', 'Mathematics', 'Psychology', 'Economics', etc."
            ),
        },
    },
    "required": ["query"],
    "additionalProperties": False,
}

GET_PAPER_DETAIL_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "paper_id": {
            "type": "string",
            "description": (
                "Semantic Scholar paper ID (e.g., 'a1b2c3d4...').  "
                "Also accepts DOI, ArXiv ID, or full URL."
            ),
        },
        "include_references": {
            "type": "boolean",
            "default": False,
            "description": (
                "If true, include the paper's reference list (outgoing citations)."
            ),
        },
    },
    "required": ["paper_id"],
    "additionalProperties": False,
}

HEALTH_CHECK_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {},
    "additionalProperties": False,
}


def create_server() -> tuple[Server, SemanticScholarClient, ResultCache]:
    """Instantiate and configure the MCP server with all tools."""

    server = Server("masa-literature-search")
    client = SemanticScholarClient()
    cache = ResultCache()

    # -- Tool listing -------------------------------------------------------

    @server.list_tools()
    async def list_tools() -> list[Tool]:
        return [
            Tool(
                name="literature_search",
                description=(
                    "Search the academic literature via Semantic Scholar.  "
                    "Returns paginated, reference-ID-tagged paper abstracts.  "
                    "Supports epistemic filtering (peer-reviewed-only vs. all) "
                    "and context-window-safe chunked pagination."
                ),
                inputSchema=LITERATURE_SEARCH_SCHEMA,
            ),
            Tool(
                name="get_paper_detail",
                description=(
                    "Fetch full metadata for a single paper by its Semantic Scholar ID.  "
                    "Use this for citation verification — confirm that a "
                    "[Reference ID: N] actually maps to a real paper.  "
                    "Optionally returns the paper's outgoing reference list."
                ),
                inputSchema=GET_PAPER_DETAIL_SCHEMA,
            ),
            Tool(
                name="health_check",
                description=(
                    "Verify that the MCP server and the upstream Semantic Scholar API "
                    "are both reachable.  Call this before starting a task pipeline "
                    "to catch network issues early."
                ),
                inputSchema=HEALTH_CHECK_SCHEMA,
            ),
        ]

    # -- Tool execution -----------------------------------------------------

    @server.call_tool()
    async def call_tool(name: str, arguments: dict[str, Any]) -> list[TextContent]:
        if name == "literature_search":
            return await _handle_literature_search(client, cache, arguments)
        elif name == "get_paper_detail":
            return await _handle_get_paper_detail(client, arguments)
        elif name == "health_check":
            return await _handle_health_check(client, cache)
        else:
            return [
                TextContent(
                    type="text",
                    text=f"[UNKNOWN_TOOL] Tool '{name}' is not registered on this server.",
                )
            ]

    return server, client, cache


# ---------------------------------------------------------------------------
# Tool handlers
# ---------------------------------------------------------------------------


def _invalid_input_response(exc: ValidationError) -> list[TextContent]:
    """Convert a Pydantic ValidationError into a tool-safe response."""
    messages: list[str] = []
    for item in exc.errors():
        field = ".".join(str(part) for part in item["loc"]) or "input"
        messages.append(f"{field}: {item['msg']}")
    detail = "; ".join(messages) if messages else "Invalid tool arguments."
    return [
        TextContent(
            type="text",
            text=f"[INVALID_INPUT] {detail}",
        )
    ]


async def _handle_literature_search(
    client: SemanticScholarClient,
    cache: ResultCache,
    arguments: dict[str, Any],
) -> list[TextContent]:
    """Handle the literature_search tool call."""

    try:
        validated = LiteratureSearchArgs.model_validate(arguments)
    except ValidationError as exc:
        return _invalid_input_response(exc)

    query = validated.query
    epistemic_filter = validated.epistemic_filter
    chunk_offset = validated.chunk_offset
    year_range = validated.year_range
    fields_of_study = validated.fields_of_study

    logger.info(
        "literature_search called — query=%r filter=%s offset=%d year=%s fields=%s",
        query,
        epistemic_filter.value,
        chunk_offset,
        year_range,
        fields_of_study,
    )

    # --- Check cache (pre-filter) ---
    cache_key = cache.make_key(query, year_range, fields_of_study)
    result = cache.get(cache_key)
    was_cache_hit = result is not None

    if result is None:
        # --- Execute upstream search ---
        try:
            result = await client.search(
                query,
                year_range=year_range,
                fields_of_study=fields_of_study,
            )
        except LiteratureSearchError as exc:
            logger.warning("Search error for query=%r: %s", query, type(exc).__name__)
            return [TextContent(type="text", text=exc.to_tool_response())]
        except Exception as exc:
            logger.exception("Unexpected error during search")
            return [
                TextContent(
                    type="text",
                    text=(
                        f"[INTERNAL_ERROR] An unexpected error occurred: {exc}\n"
                        "Action: Report this to the operator.  "
                        "Retry with a simpler query or wait before retrying."
                    ),
                )
            ]

        # --- Store in cache (pre-filter result) ---
        cache.put(cache_key, result)
    else:
        logger.info("Cache hit for query=%r", query)

    # --- Epistemic Filter (server-side enforcement) ---
    preprints_removed = 0
    if epistemic_filter == EpistemicFilter.PEER_REVIEWED_ONLY:
        pre_filter_count = len(result.papers)
        result.papers = [p for p in result.papers if not p.is_preprint]
        preprints_removed = pre_filter_count - len(result.papers)
        if preprints_removed > 0:
            logger.info(
                "Epistemic filter removed %d pre-print(s) from %d results",
                preprints_removed,
                pre_filter_count,
            )

    total_after_filter = len(result.papers)

    # --- Zero-result handling ---
    if total_after_filter == 0:
        err = ZeroResults(
            query=query,
            epistemic_filter=epistemic_filter.value,
            had_preprints=preprints_removed,
        )
        return [TextContent(type="text", text=err.to_tool_response())]

    # --- Chunk pagination (context window protection) ---
    if chunk_offset >= total_after_filter:
        return [
            TextContent(
                type="text",
                text=(
                    f"[INVALID_OFFSET] chunk_offset={chunk_offset} exceeds "
                    f"the total eligible papers ({total_after_filter}).\n"
                    "Action: Use chunk_offset=0 to start from the beginning."
                ),
            )
        ]

    page = result.papers[chunk_offset : chunk_offset + CHUNK_SIZE]

    # --- Format response ---
    response_text = format_search_response(
        papers=page,
        chunk_offset=chunk_offset,
        total_after_filter=total_after_filter,
        total_upstream=result.total_upstream,
        query=query,
        epistemic_filter=epistemic_filter.value,
        elapsed_ms=result.elapsed_ms,
        preprints_removed=preprints_removed,
        cache_hit=was_cache_hit,
    )

    logger.info(
        "Returning %d paper(s) [offset=%d, total=%d, preprints_removed=%d, cache=%s]",
        len(page),
        chunk_offset,
        total_after_filter,
        preprints_removed,
        was_cache_hit,
    )

    return [TextContent(type="text", text=response_text)]


async def _handle_get_paper_detail(
    client: SemanticScholarClient,
    arguments: dict[str, Any],
) -> list[TextContent]:
    """Handle the get_paper_detail tool call."""

    try:
        validated = GetPaperDetailArgs.model_validate(arguments)
    except ValidationError as exc:
        return _invalid_input_response(exc)

    paper_id = validated.paper_id
    include_references = validated.include_references

    logger.info(
        "get_paper_detail called — paper_id=%r include_references=%s",
        paper_id,
        include_references,
    )

    t0 = time.monotonic()
    try:
        paper, references = await client.get_paper(
            paper_id, include_references=include_references
        )
    except LiteratureSearchError as exc:
        logger.warning("Paper detail error for id=%r: %s", paper_id, type(exc).__name__)
        return [TextContent(type="text", text=exc.to_tool_response())]
    except Exception as exc:
        logger.exception("Unexpected error during paper detail lookup")
        return [
            TextContent(
                type="text",
                text=(
                    f"[INTERNAL_ERROR] An unexpected error occurred: {exc}\n"
                    "Action: Report this to the operator.  "
                    "Verify the paper ID format and retry."
                ),
            )
        ]

    elapsed = (time.monotonic() - t0) * 1000

    response_text = format_paper_detail_response(paper, references, elapsed)

    logger.info(
        "Returning paper detail [id=%s, refs=%d]",
        paper.paper_id,
        len(references),
    )

    return [TextContent(type="text", text=response_text)]


async def _handle_health_check(
    client: SemanticScholarClient,
    cache: ResultCache,
) -> list[TextContent]:
    """Handle the health_check tool call."""

    logger.info("health_check called")

    reachable, latency_ms = await client.ping()

    lines: list[str] = [
        "=" * 60,
        "MASA Literature Search — Health Check",
        "=" * 60,
        f"Server Version: {SERVER_VERSION}",
        f"Server Status: operational",
        f"Cache Entries: {cache.size} / {cache.MAX_ENTRIES}",
        f"Cache TTL: {cache.TTL}s",
        "-" * 60,
        f"Upstream API: Semantic Scholar Academic Graph",
        f"Reachable: {'YES' if reachable else 'NO'}",
        f"Latency: {latency_ms:.0f} ms",
    ]

    if SEMANTIC_SCHOLAR_KEY:
        lines.append("API Key: configured")
    else:
        lines.append("API Key: not set (using free tier rate limits)")

    if not reachable:
        lines.append("")
        lines.append(
            "[WARNING] Upstream API is not reachable.  "
            "Literature search calls will fail until connectivity is restored."
        )

    lines.append("=" * 60)

    return [TextContent(type="text", text="\n".join(lines))]


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------


async def main() -> None:
    """Run the MCP server over stdio transport."""
    server, client, cache = create_server()
    logger.info("MASA Literature Search MCP Server v%s starting (stdio transport)", SERVER_VERSION)
    logger.info("CHUNK_SIZE=%d, TIMEOUT=%ss, MAX_RESULTS=%d", CHUNK_SIZE, REQUEST_TIMEOUT, MAX_TOTAL_RESULTS)

    try:
        async with stdio_server() as (read_stream, write_stream):
            await server.run(
                read_stream,
                write_stream,
                server.create_initialization_options(),
            )
    finally:
        await client.close()
        logger.info("SemanticScholarClient closed cleanly")


if __name__ == "__main__":
    asyncio.run(main())
