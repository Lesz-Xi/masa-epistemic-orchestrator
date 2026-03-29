# Codex stdio MCP configuration

Use the stdio server:

```text
Name: masa-literature-search
Transport: STDIO
Command: /absolute/path/to/.venv/bin/python
Arguments: /absolute/path/to/masa_mcp/literature_search_server.py
Working directory: /absolute/path/to/repo
```

After a tool call returns, route the result into `TaskExecutionSession.ingest_tool_output("literature_search", tool_result)`.
