// ============================================================================
// MASA Operator Console — Domain Types
// Mirrors the Python orchestrator models in orchestrator/models.py
// ============================================================================

export type TaskStatus =
  | "pending"
  | "running"
  | "validating"
  | "fixing"
  | "succeeded"
  | "failed_terminal"
  | "escalated";

export type ErrorType =
  | "PydanticValidationError"
  | "EpistemicBoundaryViolation"
  | "LogicFailure"
  | "JSONParseError"
  | "ClientError";

export interface ScientificTask {
  taskId: string;
  objective: string;
  requiredTools: string[];
  outputSchemaName: string;
  status: TaskStatus;
  attemptCount: number;
  maxAttempts: number;
  createdAt: string; // ISO 8601
}

export interface EvidenceItem {
  referenceId: number;
  claim: string;
  strength: "strong" | "moderate" | "weak";
  quote?: string;
}

export interface WorkerResult {
  taskId: string;
  summary: string;
  evidence: EvidenceItem[];
  confidence: number;
  reasoningChain: string[];
  citedReferenceIds: number[];
}

export interface ExecutionConfig {
  temperature: number;
  top_p: number;
  top_k: number;
  seed?: number;
  response_format: { type: string };
}

export interface AttemptRecord {
  attemptNumber: number;
  promptSent: string;
  rawResponse: string;
  validationPassed: boolean;
  errorTrace?: string;
  fixerDiagnostics?: {
    failure_point: string;
    correction_strategy: string;
  };
  rewrittenPrompt?: string;
  configUsed: ExecutionConfig;
  timestamp: string;
  latencyMs: number;
  tokensUsed: number;
  ttftMs: number;
  totalMs: number;
  tokensInput: number;
  tokensOutput: number;
  costUsd: number;
}

export interface TaskExecutionLog {
  task: ScientificTask;
  attempts: AttemptRecord[];
  finalResult?: WorkerResult;
  escalationPayload?: TracePayload;
}

export interface TracePayload {
  taskId: string;
  workerObjective: string;
  errorType: ErrorType;
  errorMessage: string;
  metrics: {
    ttft: number;
    tps: number;
    cost: number;
  };
  attemptedReasoning: string[];
}

// SSE event types from orchestrator
export type SSEEvent =
  | { type: "task_created"; data: ScientificTask }
  | { type: "attempt_started"; data: { taskId: string; attemptNumber: number; config: ExecutionConfig } }
  | { type: "attempt_completed"; data: AttemptRecord & { taskId: string } }
  | { type: "fixer_invoked"; data: { taskId: string; diagnostics: { failure_point: string; correction_strategy: string } } }
  | { type: "task_succeeded"; data: { taskId: string; result: WorkerResult } }
  | { type: "task_escalated"; data: { taskId: string; payload: TracePayload } }
  | { type: "cost_update"; data: { taskId: string; totalCost: number } };

// Navigation
export type ViewId = "pipeline" | "escalations" | "tools";
