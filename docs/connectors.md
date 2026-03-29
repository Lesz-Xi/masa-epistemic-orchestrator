# Connectors

## Codex

Codex connects through the stdio MCP server in `masa_mcp/literature_search_server.py`.

The returned tool result is typically surfaced as text content blocks. `TaskExecutionSession.ingest_tool_output()` accepts that shape directly.

## Claude

Claude connects through the remote HTTP MCP transport in `masa_mcp/http_server.py`.

The returned tool result is often surfaced as a `content` envelope containing text blocks. `TaskExecutionSession.ingest_tool_output()` accepts that shape directly.

## Shared Contract

Both domains must route server-owned `literature_search` output into the same runtime session before the Worker is allowed to execute.
