"""
MASA MCP HTTP Server — Remote Transport with OAuth 2.0
=======================================================

Exposes the MASA literature_search tool over HTTP+SSE transport so Claude.ai
can connect to it as a remote MCP connector.

Auth: OAuth 2.0 Client Credentials Grant (RFC 6749 §4.4)
  - Claude sends client_id + client_secret to POST /oauth/token
  - Server returns a bearer access_token
  - Claude includes Authorization: Bearer <token> on all MCP requests
  - Token is HMAC-SHA256 signed, stateless, 1-hour TTL

Transport: MCP SSE transport
  - GET  /sse       — SSE stream (server → client)
  - POST /messages/ — JSON-RPC messages (client → server)

Setup:
  Set in .env:
    MCP_CLIENT_ID=masa-client
    MCP_CLIENT_SECRET=<generate with: openssl rand -hex 32>
    MCP_TOKEN_SECRET=<generate with: openssl rand -hex 32>

Usage for Claude.ai connector:
  Remote MCP server URL: http://<droplet-ip>:3202
  OAuth Client ID:       <MCP_CLIENT_ID>
  OAuth Client Secret:   <MCP_CLIENT_SECRET>
"""

from __future__ import annotations

import hashlib
import hmac
import json
import logging
import os
import sys
import time
from typing import Any

import httpx
import uvicorn
from mcp.server import Server
from mcp.server.sse import SseServerTransport
from mcp.types import TextContent, Tool
from pydantic import ValidationError
from starlette.applications import Starlette
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse, Response
from starlette.routing import Mount, Route

from masa_mcp.transport_schemas import LiteratureSearchArgs

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

MCP_CLIENT_ID: str = os.getenv("MCP_CLIENT_ID", "masa-client")
MCP_CLIENT_SECRET: str = os.getenv("MCP_CLIENT_SECRET", "")
MCP_TOKEN_SECRET: str = os.getenv("MCP_TOKEN_SECRET", "")
MCP_PORT: int = int(os.getenv("MCP_PORT", "3202"))
TOKEN_TTL: int = 3600  # 1 hour

SEMANTIC_SCHOLAR_BASE = "https://api.semanticscholar.org/graph/v1"
SEMANTIC_SCHOLAR_KEY: str | None = os.getenv("SEMANTIC_SCHOLAR_API_KEY")
REQUEST_TIMEOUT: float = float(os.getenv("MASA_REQUEST_TIMEOUT", "30"))
CHUNK_SIZE: int = int(os.getenv("MASA_CHUNK_SIZE", "3"))
MAX_TOTAL_RESULTS: int = int(os.getenv("MASA_MAX_TOTAL_RESULTS", "100"))

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s — %(message)s",
    stream=sys.stderr,
)
logger = logging.getLogger("masa.mcp_http")


# ---------------------------------------------------------------------------
# Token utilities — stateless HMAC-based bearer tokens
# ---------------------------------------------------------------------------


def _issue_token(client_id: str) -> tuple[str, int]:
    """
    Issue a time-bound bearer token.

    Token format: base64url( HMAC-SHA256( "<client_id>:<issued_at>", secret ) )
    We encode issued_at so we can verify expiry without a session store.
    Returns (token_string, expires_in_seconds).
    """
    if not MCP_TOKEN_SECRET:
        raise RuntimeError("MCP_TOKEN_SECRET is not set — cannot issue tokens")

    issued_at = int(time.time())
    payload = f"{client_id}:{issued_at}"
    sig = hmac.new(
        MCP_TOKEN_SECRET.encode(),
        payload.encode(),
        hashlib.sha256,
    ).hexdigest()
    token = f"{payload}:{sig}"
    return token, TOKEN_TTL


def _verify_token(token: str) -> bool:
    """
    Verify a bearer token: signature matches and not expired.
    """
    if not MCP_TOKEN_SECRET:
        return False
    try:
        parts = token.split(":")
        if len(parts) != 3:
            return False
        client_id, issued_at_str, sig = parts
        issued_at = int(issued_at_str)

        # Check expiry
        if time.time() - issued_at > TOKEN_TTL:
            logger.warning("Token expired for client_id=%s", client_id)
            return False

        # Verify signature
        payload = f"{client_id}:{issued_at_str}"
        expected_sig = hmac.new(
            MCP_TOKEN_SECRET.encode(),
            payload.encode(),
            hashlib.sha256,
        ).hexdigest()

        return hmac.compare_digest(sig, expected_sig)
    except Exception:
        return False


# ---------------------------------------------------------------------------
# OAuth 2.0 endpoints
# ---------------------------------------------------------------------------


async def oauth_token(request: Request) -> Response:
    """
    POST /oauth/token
    Implements RFC 6749 §4.4 Client Credentials Grant.

    Expected body (application/x-www-form-urlencoded or JSON):
      grant_type=client_credentials
      client_id=masa-client
      client_secret=<secret>
    """
    content_type = request.headers.get("content-type", "")

    if "application/json" in content_type:
        try:
            body = await request.json()
        except Exception:
            return JSONResponse({"error": "invalid_request"}, status_code=400)
    else:
        # application/x-www-form-urlencoded
        form = await request.form()
        body = dict(form)

    grant_type = body.get("grant_type", "")
    client_id = body.get("client_id", "")
    client_secret = body.get("client_secret", "")

    # Validate grant type
    if grant_type != "client_credentials":
        return JSONResponse(
            {"error": "unsupported_grant_type"},
            status_code=400,
        )

    # Validate credentials — constant-time comparison
    id_ok = hmac.compare_digest(client_id, MCP_CLIENT_ID)
    secret_ok = hmac.compare_digest(client_secret, MCP_CLIENT_SECRET) if MCP_CLIENT_SECRET else False

    if not id_ok or not secret_ok:
        logger.warning("OAuth: invalid credentials for client_id=%s", client_id)
        return JSONResponse(
            {"error": "invalid_client"},
            status_code=401,
        )

    token, expires_in = _issue_token(client_id)
    logger.info("OAuth: issued token for client_id=%s", client_id)

    return JSONResponse({
        "access_token": token,
        "token_type": "bearer",
        "expires_in": expires_in,
        "scope": "mcp:tools",
    })


async def oauth_discovery(_request: Request) -> Response:
    """
    GET /.well-known/oauth-authorization-server
    RFC 8414 discovery document so Claude can auto-discover the token endpoint.
    """
    host = os.getenv("MCP_PUBLIC_HOST", f"http://localhost:{MCP_PORT}")
    return JSONResponse({
        "issuer": host,
        "token_endpoint": f"{host}/oauth/token",
        "grant_types_supported": ["client_credentials"],
        "token_endpoint_auth_methods_supported": ["client_secret_post"],
        "scopes_supported": ["mcp:tools"],
    })


async def healthcheck(_request: Request) -> Response:
    """GET /health — liveness probe for Docker."""
    return JSONResponse({"status": "ok", "server": "masa-mcp-http", "version": "2.0.0"})


# ---------------------------------------------------------------------------
# Auth middleware — protects all /sse and /messages routes
# ---------------------------------------------------------------------------


class BearerAuthMiddleware(BaseHTTPMiddleware):
    """
    Validates Authorization: Bearer <token> on MCP transport routes.
    OAuth and health endpoints are exempted.
    """

    EXEMPT_PATHS = {"/oauth/token", "/.well-known/oauth-authorization-server", "/health"}

    async def dispatch(self, request: Request, call_next):
        if request.url.path in self.EXEMPT_PATHS:
            return await call_next(request)

        auth_header = request.headers.get("authorization", "")
        if not auth_header.startswith("Bearer "):
            return JSONResponse(
                {"error": "unauthorized", "detail": "Missing or invalid Authorization header"},
                status_code=401,
            )

        token = auth_header.removeprefix("Bearer ").strip()
        if not _verify_token(token):
            logger.warning("Auth: invalid/expired token from %s", request.client)
            return JSONResponse(
                {"error": "unauthorized", "detail": "Token invalid or expired"},
                status_code=401,
            )

        return await call_next(request)


# ---------------------------------------------------------------------------
# Literature search — adapted from literature_search_server.py
# ---------------------------------------------------------------------------


def _is_preprint(pub_types: list[str], venue: str) -> bool:
    lowered = [t.lower() for t in pub_types]
    if "preprint" in lowered:
        return True
    if not venue and "journalarticle" not in lowered and "conference" not in lowered:
        return True
    return False


async def _search_semantic_scholar(
    query: str,
    year_range: str | None = None,
    fields_of_study: list[str] | None = None,
    limit: int = 20,
) -> list[dict[str, Any]]:
    """Query Semantic Scholar and return raw paper dicts."""
    params: dict[str, Any] = {
        "query": query,
        "limit": min(limit, MAX_TOTAL_RESULTS),
        "fields": "paperId,title,abstract,authors,year,venue,citationCount,isOpenAccess,publicationTypes,externalIds",
    }
    if year_range:
        params["year"] = year_range
    if fields_of_study:
        params["fieldsOfStudy"] = ",".join(fields_of_study)

    headers = {}
    if SEMANTIC_SCHOLAR_KEY:
        headers["x-api-key"] = SEMANTIC_SCHOLAR_KEY

    async with httpx.AsyncClient(timeout=REQUEST_TIMEOUT) as client:
        resp = await client.get(
            f"{SEMANTIC_SCHOLAR_BASE}/paper/search",
            params=params,
            headers=headers,
        )
        resp.raise_for_status()
        data = resp.json()
        return data.get("data", [])


def _format_paper(paper: dict[str, Any], ref_id: int, peer_reviewed_only: bool) -> str | None:
    """
    Format a single paper block with [Reference ID: N] injection.
    Returns None if the paper is filtered by the epistemic wall.
    """
    pub_types = paper.get("publicationTypes") or []
    venue = paper.get("venue") or ""

    if peer_reviewed_only and _is_preprint(pub_types, venue):
        return None

    authors_raw = paper.get("authors") or []
    authors = ", ".join(a.get("name", "") for a in authors_raw[:3])
    if len(authors_raw) > 3:
        authors += " et al."

    title = paper.get("title") or "Untitled"
    year = paper.get("year") or "Unknown"
    citations = paper.get("citationCount") or 0
    abstract = (paper.get("abstract") or "No abstract available.")[:400]
    oa = "Open Access" if paper.get("isOpenAccess") else "Subscription"
    url = f"https://www.semanticscholar.org/paper/{paper.get('paperId', '')}"

    return (
        f"[Reference ID: {ref_id}]\n"
        f"Title: {title}\n"
        f"Authors: {authors}\n"
        f"Year: {year} | Venue: {venue or 'Unknown'} | Citations: {citations} | {oa}\n"
        f"Semantic Scholar ID: {paper.get('paperId', '')}\n"
        f"Abstract: {abstract}\n"
        f"URL: {url}"
    )


def _invalid_input_text(exc: ValidationError) -> str:
    """Convert a Pydantic ValidationError into a stable tool error string."""
    messages: list[str] = []
    for item in exc.errors():
        field = ".".join(str(part) for part in item["loc"]) or "input"
        messages.append(f"{field}: {item['msg']}")
    detail = "; ".join(messages) if messages else "Invalid tool arguments."
    return f"[INVALID_INPUT] {detail}"


def _format_literature_search_output(
    query: str,
    epistemic_filter: str,
    chunk_offset: int,
    formatted: list[tuple[int, str]],
) -> str:
    """Render the transport-safe literature search result block."""
    if chunk_offset >= len(formatted):
        return (
            f"[INVALID_OFFSET] chunk_offset={chunk_offset} is past the end of results "
            f"({len(formatted)} papers total). ACTION: Use chunk_offset between 0 and "
            f"{max(0, len(formatted) - 1)}."
        )

    page = formatted[chunk_offset : chunk_offset + CHUNK_SIZE]
    ref_ids_on_page = [rid for rid, _ in page]
    start_human = chunk_offset + 1
    end_human = chunk_offset + len(page)
    blocks = "\n\n---\n\n".join(block for _, block in page)

    output = (
        f"QUERY: {query}\n"
        f"FILTER: {epistemic_filter}\n"
        f"SHOWING: {start_human}-{end_human} of {len(formatted)} after filtering\n"
        f"REFERENCE IDs ON THIS PAGE: {ref_ids_on_page}\n\n"
        f"{'=' * 60}\n\n"
        f"{blocks}\n\n"
        f"{'=' * 60}\n\n"
        f"CITATION CONTRACT: You MUST only cite [Reference ID: N] values "
        f"from the list above: {ref_ids_on_page}. "
        f"Do NOT fabricate reference IDs. "
    )
    if end_human < len(formatted):
        output += (
            f"If you need more results, call literature_search again with "
            f"chunk_offset={chunk_offset + len(page)}."
        )
    else:
        output += "All matching papers have been returned."
    return output


async def execute_literature_search(arguments: dict[str, Any]) -> str:
    """Execute the HTTP transport literature search contract."""
    args = LiteratureSearchArgs.model_validate(arguments)

    logger.info(
        "literature_search: query=%r filter=%s offset=%d",
        args.query[:80], args.epistemic_filter.value, args.chunk_offset,
    )

    raw_papers = await _search_semantic_scholar(
        query=args.query,
        year_range=args.year_range,
        fields_of_study=args.fields_of_study,
        limit=MAX_TOTAL_RESULTS,
    )

    if not raw_papers:
        return (
            "ERROR_TYPE: ZeroResults\n"
            f"No papers found for query: '{args.query}'\n"
            "ACTION: Broaden the query, remove niche terminology, or try synonyms."
        )

    peer_reviewed_only = args.epistemic_filter.value == "peer_reviewed_only"
    formatted: list[tuple[int, str]] = []
    next_ref_id = 1
    filtered_count = 0
    for paper in raw_papers:
        block = _format_paper(paper, next_ref_id, peer_reviewed_only)
        if block is None:
            filtered_count += 1
            continue
        formatted.append((next_ref_id, block))
        next_ref_id += 1

    if not formatted:
        return (
            "ERROR_TYPE: ZeroResults\n"
            f"All {len(raw_papers)} results were filtered by epistemic_filter="
            f"'{args.epistemic_filter.value}'.\n"
            "ACTION: Try epistemic_filter='all' or broaden the query."
        )

    output = _format_literature_search_output(
        query=args.query,
        epistemic_filter=args.epistemic_filter.value,
        chunk_offset=args.chunk_offset,
        formatted=formatted,
    )
    if filtered_count > 0:
        output = (
            f"PREPRINTS REMOVED: {filtered_count}\n"
            f"{output}"
        )
    return output


# ---------------------------------------------------------------------------
# MCP Server definition
# ---------------------------------------------------------------------------


def build_mcp_server() -> Server:
    """Construct and return the configured MCP Server instance."""
    server = Server("masa-literature-search")

    @server.list_tools()
    async def list_tools() -> list[Tool]:
        return [
            Tool(
                name="literature_search",
                description=(
                    "Search peer-reviewed scientific literature via Semantic Scholar. "
                    "Returns papers with [Reference ID: N] markers for citation contracts. "
                    "Use epistemic_filter='peer_reviewed_only' to strip preprints. "
                    "Use chunk_offset for pagination across large result sets."
                ),
                inputSchema={
                    "type": "object",
                    "properties": {
                        "query": {
                            "type": "string",
                            "description": "Search query (title, abstract, keywords)",
                        },
                        "epistemic_filter": {
                            "type": "string",
                            "enum": ["all", "peer_reviewed_only"],
                            "default": "peer_reviewed_only",
                            "description": "Filter out preprints when set to peer_reviewed_only",
                        },
                        "chunk_offset": {
                            "type": "integer",
                            "default": 0,
                            "minimum": 0,
                            "description": (
                                "Absolute pagination offset into the filtered result set. "
                                "Each page returns at most CHUNK_SIZE papers."
                            ),
                        },
                        "year_range": {
                            "type": "string",
                            "description": "Year filter e.g. '2018-2024' or '2020-'",
                        },
                        "fields_of_study": {
                            "type": "array",
                            "items": {"type": "string"},
                            "description": "Filter by field e.g. ['Biology', 'Medicine']",
                        },
                    },
                    "required": ["query"],
                    "additionalProperties": False,
                },
            ),
            Tool(
                name="health_check",
                description="Check MCP server liveness and configuration.",
                inputSchema={"type": "object", "properties": {}},
            ),
        ]

    @server.call_tool()
    async def call_tool(name: str, arguments: dict[str, Any]) -> list[TextContent]:
        if name == "health_check":
            return [TextContent(
                type="text",
                text=json.dumps({
                    "status": "ok",
                    "server": "masa-mcp-http",
                    "version": "2.0.0",
                    "chunk_size": CHUNK_SIZE,
                    "epistemic_wall": "active",
                }),
            )]

        if name != "literature_search":
            return [TextContent(type="text", text=f"ERROR: Unknown tool '{name}'")]

        try:
            output = await execute_literature_search(arguments)
        except ValidationError as exc:
            return [TextContent(type="text", text=_invalid_input_text(exc))]
        except httpx.HTTPStatusError as exc:
            if exc.response.status_code == 429:
                return [TextContent(type="text", text=(
                    "ERROR_TYPE: RateLimited\n"
                    "The Semantic Scholar API rate limit has been reached.\n"
                    "ACTION: Wait 60 seconds before retrying. Do not modify the query."
                ))]
            return [TextContent(type="text", text=(
                f"ERROR_TYPE: UpstreamServerError\n"
                f"HTTP {exc.response.status_code} from Semantic Scholar.\n"
                f"ACTION: Simplify the query and retry."
            ))]
        except httpx.TimeoutException:
            return [TextContent(type="text", text=(
                "ERROR_TYPE: UpstreamTimeout\n"
                "Semantic Scholar did not respond within the timeout window.\n"
                "ACTION: Retry with a simpler query or reduced scope."
            ))]
        except Exception as exc:
            logger.exception("Unexpected error in literature_search")
            return [TextContent(type="text", text=f"ERROR_TYPE: InternalError\nDetail: {exc}")]

        return [TextContent(type="text", text=output)]

    return server


# ---------------------------------------------------------------------------
# App assembly
# ---------------------------------------------------------------------------


def build_app() -> Starlette:
    """Wire the MCP server, SSE transport, and auth middleware into a Starlette app."""

    if not MCP_CLIENT_SECRET:
        logger.error("MCP_CLIENT_SECRET is not set — server will reject all token requests")
    if not MCP_TOKEN_SECRET:
        logger.error("MCP_TOKEN_SECRET is not set — token signing is disabled")

    mcp_server = build_mcp_server()
    sse_transport = SseServerTransport("/messages/")

    async def handle_sse(request: Request):
        async with sse_transport.connect_sse(
            request.scope, request.receive, request._send
        ) as streams:
            await mcp_server.run(
                streams[0],
                streams[1],
                mcp_server.create_initialization_options(),
            )

    routes = [
        Route("/.well-known/oauth-authorization-server", oauth_discovery, methods=["GET"]),
        Route("/oauth/token", oauth_token, methods=["POST"]),
        Route("/health", healthcheck, methods=["GET"]),
        Route("/sse", handle_sse, methods=["GET"]),
        Mount("/messages/", app=sse_transport.handle_post_message),
    ]

    app = Starlette(routes=routes)
    app.add_middleware(BearerAuthMiddleware)

    return app


app = build_app()


if __name__ == "__main__":
    logger.info("Starting MASA MCP HTTP Server on port %d", MCP_PORT)
    uvicorn.run(
        "masa_mcp.http_server:app",
        host="0.0.0.0",
        port=MCP_PORT,
        log_level="info",
    )
