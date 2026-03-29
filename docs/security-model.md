# Security Model

This project enforces epistemic constraints, not general-purpose agent safety.

Its main security properties are:

- malformed MCP inputs are rejected at the transport boundary
- the retrieval layer constrains pagination and filter semantics
- served references are treated as server-owned provenance
- citation validation fails closed if provenance is absent
- fallback retries are deterministic and auditable
- escalation traces preserve the last known failure context for review

This repository should be deployed with standard secret hygiene for OAuth credentials, API keys, and environment files.
