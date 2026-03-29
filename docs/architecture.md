# Architecture

MASA Epistemic Orchestrator has three runtime domains:

- MCP retrieval transports in `masa_mcp/`
- orchestration and validation in `orchestrator/`
- operator visibility in `console/`

The key trust boundary is `TaskExecutionSession` in `orchestrator/runtime.py`.

The session receives server-owned literature tool output, normalizes it across Codex and Claude result shapes, constructs the authoritative served-reference ledger, and only then allows `execute_task()` to invoke the Worker.

That design makes provenance enforcement explicit and fail-closed.
