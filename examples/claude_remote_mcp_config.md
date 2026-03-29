# Claude remote MCP configuration

Expose the HTTP MCP transport from:

```text
python -m masa_mcp.http_server
```

Configure Claude with:

```text
Remote MCP URL: https://<your-host>:3202
OAuth Client ID: <MCP_CLIENT_ID>
OAuth Client Secret: <MCP_CLIENT_SECRET>
```

When Claude returns `literature_search` content, pass the raw tool payload into `TaskExecutionSession.ingest_tool_output("literature_search", tool_result)`.
