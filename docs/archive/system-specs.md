# MASA Orchestrator v2 — System Specs

Three sequential implementation specs for the epistemic wall pipeline.
Each spec covers: current state, target architecture, data contracts, implementation plan, and open questions.

---

## Spec 1: MCP Server Extension

### Current State

`literature_search_server.py` is implemented and verified. It provides:

- One tool (`literature_search`) with five parameters: `query`, `epistemic_filter`, `chunk_offset`, `year_range`, `fields_of_study`
- Server-side preprint filtering via `Paper.is_preprint` heuristic
- Strict `CHUNK_SIZE` pagination (default 3) with explicit `chunk_offset` hints
- `[Reference ID: N]` injection on every paper
- Five structured error classes, each returning an LLM-readable diagnostic string with `Action:` directives
- Semantic Scholar Academic Graph API backend via `httpx.AsyncClient`
- stdio transport via MCP SDK

### What's Missing

| Gap | Severity | Rationale |
|-----|----------|-----------|
| No live API integration test | High | We verified imports and logic in-process but never hit the real Semantic Scholar endpoint |
| No caching layer | Medium | Repeated queries from fallback retries re-hit the API, wasting rate budget |
| `SemanticScholarClient` never calls `close()` | Medium | httpx client leaks on server shutdown |
| No `get_paper_by_id` tool | Medium | Fixer Agent may need to fetch a specific paper by Semantic Scholar ID for citation verification |
| No `search_by_citations` tool | Low | Forward/backward citation traversal is needed for causal chain discovery but not for v2 MVP |
| No HTTP transport option | Low | stdio is sufficient for single-client orchestrator; HTTP needed only for multi-client |

### Target Architecture

```
┌─────────────────────────────────────────────────┐
│  MCP Server: masa-literature-search             │
│                                                 │
│  Tools:                                         │
│    ├─ literature_search        (implemented)    │
│    ├─ get_paper_detail         (new)            │
│    └─ health_check             (new)            │
│                                                 │
│  Internal:                                      │
│    ├─ SemanticScholarClient    (extend)         │
│    ├─ ResultCache              (new)            │
│    └─ EpistemicFilter          (implemented)    │
│                                                 │
│  Transport: stdio (default), HTTP (optional)    │
└─────────────────────────────────────────────────┘
```

### New Tool: `get_paper_detail`

Purpose: Given a Semantic Scholar paper ID, return the full metadata for a single paper. This is critical for citation verification — the Worker produces `[Reference ID: 3]` in its output, and the orchestrator needs to verify that reference actually exists.

```json
{
  "name": "get_paper_detail",
  "inputSchema": {
    "type": "object",
    "properties": {
      "paper_id": {
        "type": "string",
        "description": "Semantic Scholar paper ID (e.g., 'a1b2c3d4...')"
      },
      "include_references": {
        "type": "boolean",
        "default": false,
        "description": "If true, include the paper's reference list (outgoing citations)"
      }
    },
    "required": ["paper_id"]
  }
}
```

Response format: Same `[Reference ID: N]` block format as `literature_search`, with `N` always `1` for single-paper lookups. If `include_references` is true, append a `REFERENCE LIST` section with numbered entries.

### New Tool: `health_check`

Purpose: Let the orchestrator verify the MCP server and upstream API are both reachable before starting a task pipeline.

```json
{
  "name": "health_check",
  "inputSchema": {
    "type": "object",
    "properties": {},
    "additionalProperties": false
  }
}
```

Response: A structured string reporting server version, upstream API reachability (ping Semantic Scholar `/paper/search?query=test&limit=1`), and current rate limit status if available.

### Result Cache Design

```python
@dataclass
class CacheEntry:
    result: SearchResult
    timestamp: float          # time.monotonic()
    epistemic_filter: str     # cache key includes filter state

class ResultCache:
    """LRU cache for Semantic Scholar queries. Keyed by (query, year_range, fields_of_study)."""

    TTL: float = 300.0       # 5 minutes — papers don't change that fast
    MAX_ENTRIES: int = 50

    def get(self, key: tuple) -> SearchResult | None: ...
    def put(self, key: tuple, result: SearchResult) -> None: ...
    def invalidate_all(self) -> None: ...
```

Cache is pre-filter. The epistemic filter runs after cache retrieval so that a cached "all" result can serve a subsequent "peer_reviewed_only" request without re-hitting the API.

### Client Lifecycle Fix

```python
def create_server() -> Server:
    server = Server("masa-literature-search")
    client = SemanticScholarClient()
    cache = ResultCache()

    # Register shutdown handler
    @server.on_close()        # or atexit if MCP SDK doesn't expose this
    async def cleanup():
        await client.close()
```

### Integration Test Plan

File: `tests/test_live_api.py`

| Test | What it proves |
|------|----------------|
| `test_basic_search` | Semantic Scholar returns data for a known query ("transformer attention mechanism") |
| `test_epistemic_filter_removes_preprints` | At least one result is filtered when `peer_reviewed_only` is active |
| `test_pagination_round_trip` | `chunk_offset=0` returns N papers, `chunk_offset=N` returns different papers |
| `test_zero_results` | Nonsense query ("xyzzy_no_match_12345") returns a `[ZERO_RESULTS]` diagnostic |
| `test_reference_id_continuity` | IDs on page 2 start where page 1 ended |
| `test_year_range_filter` | Papers returned are within the specified year range |
| `test_rate_limit_handling` | (Skip in CI) If rate-limited, error response contains `[RATE_LIMITED]` |

Run: `pytest tests/test_live_api.py -v --timeout=60`

Mark all tests with `@pytest.mark.integration` so they can be excluded from unit runs.

### Implementation Priority

1. **Client lifecycle fix** — 15 min, prevents connection leaks
2. **Integration test suite** — 1 hr, validates the entire stack against live API
3. **Result cache** — 1 hr, critical for fallback loop efficiency
4. **`get_paper_detail` tool** — 30 min, needed by the Fixer Agent for citation verification
5. **`health_check` tool** — 15 min, nice-to-have for pipeline startup

---

## Spec 2: Fixer Agent Loop (Orchestration Engine)

### Current State

Three disconnected prototype files:

| File | Contains | Status |
|------|----------|--------|
| `PRNG/context-config.py` | `EXPLORATION_CONFIG` and `FALLBACK_CONFIG` dicts | Config only, no consumers |
| `PRNG/validate-error.py` | `generate_deterministic_seed()` and `execute_with_epistemic_lock()` | References `ScientificTask`, `llm_client`, `EXPLORATION_CONFIG` — none exist |
| `fixer-agent.py` | `generate_fixer_prompt()` template | Prompt template only, no caller |

No orchestration loop, no validation layer, no retry counter, no escalation path, no Pydantic models, no LLM client abstraction.

### Target Architecture

```
┌─────────────────────────────────────────────────────────────┐
│  Orchestrator Engine                                        │
│                                                             │
│  ┌──────────┐    ┌──────────┐    ┌──────────┐              │
│  │  Task     │───▶│  Worker   │───▶│ Validator │             │
│  │  Queue    │    │  Executor │    │  (Pydantic)│            │
│  └──────────┘    └──────────┘    └─────┬─────┘             │
│                                        │                    │
│                         ┌──────────────┼──────────────┐     │
│                         │ pass         │ fail          │     │
│                         ▼              ▼              │     │
│                   ┌──────────┐   ┌──────────┐        │     │
│                   │  Result   │   │  Fixer    │        │     │
│                   │  Store    │   │  Agent    │        │     │
│                   └──────────┘   └─────┬─────┘        │     │
│                                        │               │     │
│                                        ▼               │     │
│                                  ┌──────────┐         │     │
│                                  │ Epistemic │─── retry ┘     │
│                                  │ Lock      │                │
│                                  └─────┬─────┘               │
│                                        │ 3 strikes           │
│                                        ▼                     │
│                                  ┌──────────┐               │
│                                  │ Escalate  │──▶ Console    │
│                                  │ to UI     │               │
│                                  └──────────┘               │
└─────────────────────────────────────────────────────────────┘
```

### Data Models

```python
# models.py

from pydantic import BaseModel, Field
from enum import Enum
from datetime import datetime
from typing import Optional


class TaskStatus(str, Enum):
    PENDING = "pending"
    RUNNING = "running"
    VALIDATING = "validating"
    FIXING = "fixing"
    SUCCEEDED = "succeeded"
    FAILED_TERMINAL = "failed_terminal"     # 3-strike exhaustion
    ESCALATED = "escalated"                  # pushed to operator console


class ScientificTask(BaseModel):
    """A unit of work assigned to a Worker agent."""
    task_id: str = Field(description="Unique identifier, used for PRNG seed derivation")
    objective: str = Field(description="Natural-language objective for the Worker")
    required_tools: list[str] = Field(default_factory=list, description="MCP tools the Worker may call")
    output_schema_name: str = Field(description="Name of the Pydantic model the output must conform to")
    status: TaskStatus = TaskStatus.PENDING
    attempt_count: int = 0
    max_attempts: int = 3
    created_at: datetime = Field(default_factory=datetime.utcnow)


class WorkerResult(BaseModel):
    """Schema the Worker MUST output. Validated by Pydantic before acceptance."""
    task_id: str
    summary: str = Field(description="1-3 sentence summary of findings")
    evidence: list[EvidenceItem] = Field(description="List of evidence items with reference IDs")
    confidence: float = Field(ge=0.0, le=1.0, description="Self-assessed confidence 0-1")
    reasoning_chain: list[str] = Field(description="Step-by-step reasoning trace")
    cited_reference_ids: list[int] = Field(description="[Reference ID: N] values used")


class EvidenceItem(BaseModel):
    """A single piece of evidence tied to a literature reference."""
    reference_id: int = Field(description="Must match a [Reference ID: N] from literature_search")
    claim: str = Field(description="The specific claim supported by this reference")
    strength: str = Field(description="'strong', 'moderate', or 'weak'")
    quote: Optional[str] = Field(default=None, description="Direct quote from the abstract, if available")


class AttemptRecord(BaseModel):
    """Immutable record of a single Worker execution attempt."""
    attempt_number: int
    prompt_sent: str
    raw_response: str
    validation_passed: bool
    error_trace: Optional[str] = None
    fixer_diagnostics: Optional[dict] = None
    rewritten_prompt: Optional[str] = None
    config_used: dict                        # EXPLORATION_CONFIG or FALLBACK_CONFIG + seed
    timestamp: datetime = Field(default_factory=datetime.utcnow)
    latency_ms: float = 0.0
    tokens_used: int = 0
    cost_usd: float = 0.0


class TaskExecutionLog(BaseModel):
    """Full execution history for a task, including all attempts."""
    task: ScientificTask
    attempts: list[AttemptRecord] = Field(default_factory=list)
    final_result: Optional[WorkerResult] = None
    escalation_payload: Optional[dict] = None   # TracePayload for the operator console
```

### LLM Client Abstraction

```python
# llm_client.py

from abc import ABC, abstractmethod
from typing import Any


class LLMClient(ABC):
    """Abstract interface for LLM providers. Swap implementations for testing."""

    @abstractmethod
    async def generate(
        self,
        prompt: str,
        *,
        temperature: float = 0.7,
        top_p: float = 0.9,
        top_k: int = 40,
        seed: int | None = None,
        response_format: dict | None = None,
        model: str | None = None,
    ) -> LLMResponse: ...


class LLMResponse(BaseModel):
    text: str
    model: str
    tokens_input: int
    tokens_output: int
    cost_usd: float
    ttft_ms: float               # Time to first token
    total_ms: float


class AnthropicClient(LLMClient):
    """Production client using Claude API."""
    ...

class GoogleClient(LLMClient):
    """Production client for Gemini (used for Fixer Agent — fast, cheap)."""
    ...

class MockClient(LLMClient):
    """Deterministic mock for testing. Returns pre-configured responses."""
    ...
```

### Orchestration Loop

```python
# orchestrator.py

async def execute_task(
    task: ScientificTask,
    worker_client: LLMClient,         # Claude for Worker
    fixer_client: LLMClient,          # Gemini Flash for Fixer
    mcp_session: MCPClientSession,    # Connected to literature_search server
) -> TaskExecutionLog:
    """
    Core orchestration loop with epistemic wall enforcement.

    Flow:
      1. Build initial Worker prompt (includes tool descriptions + output schema)
      2. Execute Worker with EXPLORATION_CONFIG
      3. Parse raw output → attempt Pydantic validation
      4. If valid: record success, return
      5. If invalid:
         a. Record attempt with error trace
         b. Send error to Fixer Agent → get rewritten prompt
         c. Lock PRNG (FALLBACK_CONFIG + deterministic seed)
         d. Re-execute Worker with rewritten prompt
         e. Repeat from step 3
      6. After max_attempts: build TracePayload, escalate to console
    """
    log = TaskExecutionLog(task=task)
    current_prompt = build_worker_prompt(task, mcp_session)

    for attempt_num in range(1, task.max_attempts + 1):
        is_retry = attempt_num > 1

        # Select execution config
        if is_retry:
            config = build_fallback_config(task.task_id)
        else:
            config = EXPLORATION_CONFIG.copy()

        # Execute Worker
        response = await worker_client.generate(
            prompt=current_prompt,
            **config,
        )

        # Validate output
        try:
            result = WorkerResult.model_validate_json(response.text)

            # Additional epistemic checks beyond schema
            verify_reference_ids_exist(result, mcp_session)
            verify_no_hallucinated_citations(result)

            # Success
            log.attempts.append(AttemptRecord(
                attempt_number=attempt_num,
                prompt_sent=current_prompt,
                raw_response=response.text,
                validation_passed=True,
                config_used=config,
                latency_ms=response.total_ms,
                tokens_used=response.tokens_input + response.tokens_output,
                cost_usd=response.cost_usd,
            ))
            log.final_result = result
            task.status = TaskStatus.SUCCEEDED
            return log

        except (ValidationError, EpistemicViolation) as exc:
            error_trace = format_error_trace(exc)

            # Record failed attempt
            attempt_record = AttemptRecord(
                attempt_number=attempt_num,
                prompt_sent=current_prompt,
                raw_response=response.text,
                validation_passed=False,
                error_trace=error_trace,
                config_used=config,
                latency_ms=response.total_ms,
                tokens_used=response.tokens_input + response.tokens_output,
                cost_usd=response.cost_usd,
            )

            # Generate fix (unless this is the last attempt)
            if attempt_num < task.max_attempts:
                task.status = TaskStatus.FIXING
                fixer_prompt = generate_fixer_prompt(
                    worker_objective=task.objective,
                    error_trace=error_trace,
                    attempted_reasoning=extract_reasoning(response.text),
                )
                fixer_response = await fixer_client.generate(
                    prompt=fixer_prompt,
                    temperature=0.0,
                    response_format={"type": "json_object"},
                )
                fixer_output = json.loads(fixer_response.text)

                attempt_record.fixer_diagnostics = fixer_output.get("diagnostics")
                attempt_record.rewritten_prompt = fixer_output.get("rewritten_prompt")
                current_prompt = fixer_output["rewritten_prompt"]

            log.attempts.append(attempt_record)

    # Exhausted all attempts — escalate
    task.status = TaskStatus.ESCALATED
    log.escalation_payload = build_trace_payload(task, log)
    return log
```

### Epistemic Checks (Beyond Schema Validation)

```python
# epistemic_checks.py

class EpistemicViolation(Exception):
    """Raised when output passes schema but violates epistemic constraints."""
    pass

def verify_reference_ids_exist(result: WorkerResult, mcp_session: MCPClientSession) -> None:
    """
    Every reference_id in cited_reference_ids must correspond to a paper
    that was actually returned by literature_search in this session.
    Prevents the Worker from fabricating reference IDs.
    """
    # The MCP session tracks which reference IDs were served
    served_ids = mcp_session.get_served_reference_ids()
    fabricated = set(result.cited_reference_ids) - served_ids
    if fabricated:
        raise EpistemicViolation(
            f"Worker cited reference IDs {fabricated} that were never "
            f"returned by literature_search. Served IDs: {served_ids}"
        )

def verify_no_hallucinated_citations(result: WorkerResult) -> None:
    """
    Each EvidenceItem.claim must not contain author names or paper titles
    that don't appear in the corresponding reference's abstract.
    (Lightweight heuristic — full verification requires get_paper_detail.)
    """
    ...
```

### File Structure

```
masa-orchestrator-mcp-v2/
├── orchestrator/
│   ├── __init__.py
│   ├── models.py              # ScientificTask, WorkerResult, EvidenceItem, AttemptRecord
│   ├── orchestrator.py        # execute_task() loop
│   ├── epistemic_checks.py    # verify_reference_ids_exist, verify_no_hallucinated_citations
│   ├── fixer.py               # generate_fixer_prompt (moved from fixer-agent.py)
│   └── config.py              # EXPLORATION_CONFIG, FALLBACK_CONFIG, generate_deterministic_seed
├── clients/
│   ├── __init__.py
│   ├── base.py                # LLMClient ABC, LLMResponse
│   ├── anthropic_client.py    # Claude API wrapper
│   ├── google_client.py       # Gemini Flash wrapper
│   └── mock_client.py         # Deterministic test client
├── literature_search_server.py  # (existing, extend per Spec 1)
├── tests/
│   ├── test_live_api.py       # Integration tests (Spec 1)
│   ├── test_orchestrator.py   # Unit tests with MockClient
│   ├── test_epistemic_checks.py
│   └── test_fixer.py
└── requirements.txt
```

### Key Design Decisions

**Why two LLM clients?** The Worker runs on Claude (best reasoning, worth the cost). The Fixer runs on Gemini Flash (fast, cheap, good enough for structured JSON repair). This is an explicit cost/latency tradeoff — the Fixer doesn't need deep reasoning, it needs speed.

**Why not use MCP for the orchestrator itself?** The orchestrator is a *client* of MCP tools, not a server. It calls `literature_search` via the MCP client protocol. The operator console connects to the orchestrator via a separate channel (SSE/WebSocket).

**Why Pydantic for validation, not JSON Schema?** Pydantic gives us Python-native validation errors with field paths, custom validators, and type coercion. The error traces feed directly into the Fixer Agent prompt. JSON Schema alone doesn't give us the diagnostic resolution we need.

### Implementation Priority

1. **`models.py`** — 1 hr, defines all data contracts, blocks everything else
2. **`config.py`** — 30 min, consolidate PRNG/config from prototype files
3. **`clients/base.py` + `mock_client.py`** — 1 hr, enables testing without API keys
4. **`orchestrator.py`** — 2 hr, core loop with MockClient
5. **`epistemic_checks.py`** — 1 hr, reference ID verification
6. **`fixer.py`** — 30 min, port and type `generate_fixer_prompt`
7. **`test_orchestrator.py`** — 2 hr, full loop tests with mock
8. **`anthropic_client.py` + `google_client.py`** — 1 hr each, production clients

### Open Questions

| Question | Options | Recommendation |
|----------|---------|----------------|
| Where does the task queue live? | In-memory list vs. SQLite vs. Redis | In-memory for v2. SQLite for persistence if we need cross-session recovery. |
| How does the orchestrator discover the MCP server? | Spawn as subprocess vs. connect to running instance | Subprocess via stdio (simple, self-contained). |
| Should the Fixer have access to MCP tools? | Yes (can re-query literature) vs. No (prompt-only repair) | No for v2. The Fixer operates on the error trace alone. Adding tool access creates a recursion risk. |
| What model for the Worker? | Claude Sonnet vs. Claude Opus | Sonnet for v2 (cost). Opus for tasks flagged as high-complexity. |

---

## Spec 3: Operator Console

### Current State

`operator-console.tsx` is a single presentational React component (`DelegationFailureTrace`) that renders a static `TracePayload` prop. It has no app shell, no routing, no data fetching, no state management, no authentication, no real-time updates, and no integration with the orchestrator backend.

### Target Architecture

```
┌──────────────────────────────────────────────────────────┐
│  Operator Console (Next.js 15)                           │
│                                                          │
│  ┌─────────┐ ┌──────────────────────────────┐ ┌───────┐ │
│  │ Sidebar  │ │ Main Workspace               │ │ Rail  │ │
│  │          │ │                              │ │       │ │
│  │ Pipeline │ │ ┌─ Active View ────────────┐ │ │ Live  │ │
│  │ Overview │ │ │                          │ │ │ Trace │ │
│  │          │ │ │ - Pipeline Monitor       │ │ │ Feed  │ │
│  │ Task     │ │ │ - Task Inspector         │ │ │       │ │
│  │ List     │ │ │ - Escalation Queue       │ │ │ Cost  │ │
│  │          │ │ │ - Tool Runner            │ │ │ Meter │ │
│  │ Filters  │ │ │                          │ │ │       │ │
│  │          │ │ └──────────────────────────┘ │ │       │ │
│  └─────────┘ └──────────────────────────────┘ └───────┘ │
│                                                          │
│  Transport: SSE from orchestrator → console              │
└──────────────────────────────────────────────────────────┘
```

### Design System Tokens (MASA-Aligned)

The console inherits the MASA design language — warm cinematic dark, instrument serif, amber accent — but adapted for an operator context where density and scannability take priority over editorial beauty.

```css
/* Console-specific token overrides */
:root {
  /* Base palette — inherited from MASA */
  --bg-base: #0E0D0C;
  --bg-surface: #161514;
  --bg-elevated: #1E1D1B;
  --bg-recessed: #0A0908;

  /* Accent */
  --accent: #C8965A;
  --accent-dim: rgba(200, 150, 90, 0.15);

  /* Text hierarchy */
  --text-primary: #F5EFE5;
  --text-secondary: #B6AB98;
  --text-tertiary: #8E8478;
  --text-dim: #6B6159;

  /* Semantic status — NEW for console */
  --status-running: #C8965A;          /* amber — in progress */
  --status-succeeded: #8CA678;        /* sage green */
  --status-failed: #D96A5D;           /* rust red */
  --status-escalated: #E8AF5E;        /* warm amber — needs attention */
  --status-fixing: #7BA3C9;           /* cool blue — fixer active */
  --status-pending: #6B6159;          /* dim — queued */

  /* Typography */
  --font-display: 'Instrument Serif', serif;
  --font-body: 'Inter', sans-serif;
  --font-mono: 'JetBrains Mono', monospace;

  /* Spacing (8px base grid) */
  --space-1: 4px;
  --space-2: 8px;
  --space-3: 12px;
  --space-4: 16px;
  --space-6: 24px;
  --space-8: 32px;

  /* Layout */
  --sidebar-w: 240px;
  --rail-w: 320px;
  --topbar-h: 42px;

  /* Radius */
  --radius-sm: 6px;
  --radius-md: 10px;
  --radius-lg: 14px;
}
```

### Views

#### 1. Pipeline Monitor (Default View)

Purpose: Real-time overview of all active task pipelines.

```
┌──────────────────────────────────────────────────┐
│  PIPELINE MONITOR                   3 active     │
│──────────────────────────────────────────────────│
│                                                  │
│  ┌─ Task-A7x ──────── ● RUNNING ──────── 1/3 ─┐│
│  │  "Identify causal factors in BRCA1 pathway"  ││
│  │  Worker: claude-sonnet  │  12.4s  │  $0.018  ││
│  └──────────────────────────────────────────────┘│
│                                                  │
│  ┌─ Task-B2m ──────── ◆ FIXING ───────── 2/3 ─┐│
│  │  "Meta-analysis of CRISPR off-target rates"  ││
│  │  Fixer: gemini-flash  │  1.2s  │  $0.0003   ││
│  │  Error: PydanticValidationError (confidence) ││
│  └──────────────────────────────────────────────┘│
│                                                  │
│  ┌─ Task-C9z ──────── ▲ ESCALATED ──── 3/3 ────┐│
│  │  "Survey immunotherapy response predictors"   ││
│  │  Exhausted 3 attempts │ Total: $0.094         ││
│  │  [Inspect] [Override & Approve] [Dismiss]     ││
│  └──────────────────────────────────────────────┘│
└──────────────────────────────────────────────────┘
```

Data source: `TaskExecutionLog[]` from orchestrator via SSE.

#### 2. Task Inspector (Drill-Down)

Purpose: Full execution history for a single task, including all attempts, fixer diagnostics, and the escalation trace.

Reuses `DelegationFailureTrace` as one section, but wraps it in a full timeline:

```
┌──────────────────────────────────────────────────┐
│  TASK INSPECTOR: Task-C9z                        │
│──────────────────────────────────────────────────│
│                                                  │
│  Objective:                                      │
│  "Survey immunotherapy response predictors"      │
│                                                  │
│  ─── Attempt 1 ─── EXPLORATION ─── 14.2s ────── │
│  Config: temp=0.7, top_p=0.9, top_k=40          │
│  Result: ✗ PydanticValidationError               │
│  Error: confidence=1.5 (must be ≤1.0)            │
│                                                  │
│  ─── Fixer Intervention ─────────────────────── │
│  Failure Point: Worker output confidence > 1.0   │
│  Strategy: Add explicit range constraint to...   │
│                                                  │
│  ─── Attempt 2 ─── FALLBACK (seed: 0xA3F2) ─── │
│  Config: temp=0.0, top_p=0.1, top_k=1           │
│  Result: ✗ EpistemicViolation                    │
│  Error: Reference ID 7 was never served          │
│                                                  │
│  ─── Fixer Intervention ─────────────────────── │
│  Failure Point: Hallucinated reference ID        │
│  Strategy: Enumerate valid IDs in prompt...      │
│                                                  │
│  ─── Attempt 3 ─── FALLBACK (seed: 0xA3F2) ─── │
│  Config: temp=0.0, top_p=0.1, top_k=1           │
│  Result: ✗ PydanticValidationError               │
│  Error: evidence[2].strength='high' not in enum  │
│                                                  │
│  ═══ ESCALATED ══════════════════════════════════│
│  Total cost: $0.094  │  Total time: 38.7s        │
│                                                  │
│  [Override & Approve] [Requeue with new prompt]  │
└──────────────────────────────────────────────────┘
```

#### 3. Escalation Queue

Purpose: Filtered view showing only `ESCALATED` and `FAILED_TERMINAL` tasks, sorted by recency. This is the operator's primary action surface.

#### 4. Tool Runner

Purpose: Manual MCP tool execution for debugging. The operator types a query, selects parameters, and sees the raw tool response. Useful for verifying that `literature_search` returns expected results before re-queuing a task.

### Component Architecture

```
console/
├── app/
│   ├── layout.tsx              # Three-zone shell
│   ├── page.tsx                # Pipeline Monitor (default)
│   ├── task/[id]/page.tsx      # Task Inspector
│   ├── escalations/page.tsx    # Escalation Queue
│   ├── tools/page.tsx          # Tool Runner
│   └── api/
│       └── events/route.ts     # SSE proxy to orchestrator
├── src/
│   ├── components/
│   │   ├── shell/
│   │   │   ├── Sidebar.tsx
│   │   │   ├── Rail.tsx
│   │   │   └── Topbar.tsx
│   │   ├── pipeline/
│   │   │   ├── TaskRow.tsx
│   │   │   ├── StatusChip.tsx
│   │   │   └── MetricsInline.tsx
│   │   ├── inspector/
│   │   │   ├── AttemptTimeline.tsx
│   │   │   ├── FixerCard.tsx
│   │   │   └── EscalationTrace.tsx    # Evolved from DelegationFailureTrace
│   │   ├── tools/
│   │   │   └── ToolRunnerPanel.tsx
│   │   └── primitives/
│   │       ├── StatusChip.tsx
│   │       ├── MetricBadge.tsx
│   │       ├── MonoBlock.tsx          # Pre-formatted code/JSON blocks
│   │       └── ActionBar.tsx          # Operator action buttons
│   ├── hooks/
│   │   ├── useSSE.ts                  # SSE connection to orchestrator
│   │   ├── useTaskStore.ts            # Zustand store for task state
│   │   └── useMCPTool.ts             # Direct MCP tool invocation
│   ├── lib/
│   │   ├── sse-client.ts
│   │   └── types.ts                   # TracePayload, TaskExecutionLog (TypeScript mirrors)
│   └── styles/
│       └── tokens.css                 # Design tokens above
├── package.json
└── next.config.ts
```

### Real-Time Data Flow

```
Orchestrator (Python)
    │
    │ SSE stream: task_update, attempt_complete, escalation, fixer_result
    │
    ▼
Next.js API route (/api/events)
    │
    │ Re-broadcasts SSE to browser
    │
    ▼
useSSE() hook → useTaskStore (Zustand)
    │
    │ Reactive state updates
    │
    ▼
Components re-render with new data
```

SSE event types:

```typescript
type SSEEvent =
  | { type: "task_created"; data: ScientificTask }
  | { type: "attempt_started"; data: { taskId: string; attemptNumber: number; config: Record<string, any> } }
  | { type: "attempt_completed"; data: AttemptRecord }
  | { type: "fixer_invoked"; data: { taskId: string; diagnostics: object } }
  | { type: "task_succeeded"; data: { taskId: string; result: WorkerResult } }
  | { type: "task_escalated"; data: { taskId: string; payload: TracePayload } }
  | { type: "cost_update"; data: { taskId: string; totalCost: number } }
```

### Operator Actions

| Action | Where | Effect |
|--------|-------|--------|
| **Override & Approve** | Escalation Queue, Task Inspector | Accept the last Worker output despite validation failure. Records operator override in audit log. |
| **Requeue with new prompt** | Task Inspector | Operator writes a manual prompt. Task re-enters the pipeline with `attempt_count` reset. |
| **Dismiss** | Escalation Queue | Mark task as `FAILED_TERMINAL` with operator acknowledgment. |
| **Trigger Manual Fixer** | Task Inspector | Run the Fixer Agent on-demand with the current error trace, without consuming an attempt. |
| **Run Tool** | Tool Runner | Execute any MCP tool manually and inspect the raw response. |

### Implementation Priority

1. **Design tokens + shell layout** — 2 hr, establishes the visual container
2. **`useSSE` hook + `useTaskStore`** — 2 hr, enables real-time data
3. **Pipeline Monitor view** — 3 hr, the default and most critical view
4. **`StatusChip` + `MetricBadge` primitives** — 1 hr, used everywhere
5. **Task Inspector view** — 3 hr, drill-down into execution history
6. **Escalation Queue view** — 1 hr, filtered view of Pipeline Monitor
7. **Tool Runner view** — 2 hr, manual debugging surface
8. **Operator action handlers** — 2 hr, Override/Requeue/Dismiss wiring

### Open Questions

| Question | Options | Recommendation |
|----------|---------|----------------|
| State management | Zustand vs. React Context vs. Redux | Zustand. Lightweight, works with SSE, no boilerplate. |
| Auth for console | Session-based (v1 pattern) vs. None (local-only) | None for v2. Console runs on localhost. Add auth when deployed. |
| How does the console send commands back to the orchestrator? | HTTP POST to orchestrator vs. Bidirectional SSE vs. WebSocket | HTTP POST. SSE is server→client only. The orchestrator exposes a small REST API for operator actions. |
| Should the console persist task history? | In-memory only vs. SQLite | In-memory for v2. The orchestrator owns persistence. Console is a view layer. |

---

## Cross-System Integration Summary

```
                    ┌────────────────────┐
                    │  Operator Console  │
                    │  (Next.js)         │
                    └────────┬───────────┘
                             │ SSE (read) + HTTP POST (actions)
                             │
                    ┌────────▼───────────┐
                    │  Orchestrator      │
                    │  Engine (Python)   │
                    │                    │
                    │  Worker ←→ Fixer   │
                    │  Validation Loop   │
                    └────────┬───────────┘
                             │ MCP stdio
                             │
                    ┌────────▼───────────┐
                    │  Literature Search │
                    │  MCP Server        │
                    └────────┬───────────┘
                             │ HTTPS
                             │
                    ┌────────▼───────────┐
                    │  Semantic Scholar  │
                    │  API               │
                    └────────────────────┘
```

### Shared Contracts

| Contract | Defined in | Consumed by |
|----------|-----------|-------------|
| `[Reference ID: N]` format | `literature_search_server.py` → `format_paper_block()` | Worker (must cite), Orchestrator (must verify) |
| `WorkerResult` schema | `orchestrator/models.py` | Worker (must output), Orchestrator (validates), Console (displays) |
| `TracePayload` interface | `orchestrator/models.py` → `build_trace_payload()` | Orchestrator (emits), Console (renders) |
| `AttemptRecord` | `orchestrator/models.py` | Orchestrator (writes), Console (displays in timeline) |
| SSE event types | `orchestrator/sse.py` | Orchestrator (emits), Console `useSSE` (consumes) |
| Fixer JSON contract | `orchestrator/fixer.py` → `generate_fixer_prompt()` | Fixer Agent (outputs), Orchestrator (parses) |

### Implementation Order (Full System)

| Phase | Work | Duration | Dependency |
|-------|------|----------|------------|
| **Phase 1** | MCP server fixes (cache, lifecycle, `get_paper_detail`) | 3 hr | None |
| **Phase 2** | `models.py` + `config.py` + `clients/mock_client.py` | 2 hr | None (parallel with Phase 1) |
| **Phase 3** | `orchestrator.py` + `epistemic_checks.py` + `fixer.py` | 4 hr | Phase 2 |
| **Phase 4** | `test_orchestrator.py` with MockClient | 2 hr | Phase 3 |
| **Phase 5** | Console shell + tokens + SSE hook | 4 hr | Phase 3 (needs SSE event types) |
| **Phase 6** | Console views (Pipeline Monitor, Task Inspector) | 6 hr | Phase 5 |
| **Phase 7** | Production LLM clients (Anthropic, Google) | 2 hr | Phase 3 |
| **Phase 8** | End-to-end integration test | 2 hr | All above |

Total estimated: ~25 hours of focused implementation.
