"use client";

import { StatusChip } from "@/components/primitives/StatusChip";
import { MetricBadge } from "@/components/primitives/MetricBadge";
import type { TaskExecutionLog } from "@/lib/types";

interface TaskRowProps {
  log: TaskExecutionLog;
  onInspect: (taskId: string) => void;
}

export function TaskRow({ log, onInspect }: TaskRowProps) {
  const { task, attempts } = log;
  const lastAttempt = attempts[attempts.length - 1];
  const totalCost = attempts.reduce((sum, a) => sum + a.costUsd, 0);
  const totalLatency = attempts.reduce((sum, a) => sum + a.latencyMs, 0);

  const configLabel =
    task.status === "running" && task.attemptCount <= 1
      ? "Exploration"
      : task.attemptCount > 1
        ? `Fallback${lastAttempt?.configUsed.seed ? ` (0x${lastAttempt.configUsed.seed.toString(16).toUpperCase()})` : ""}`
        : "";

  const workerLabel =
    task.status === "fixing"
      ? "gemini-flash"
      : "claude-sonnet";

  return (
    <button
      onClick={() => onInspect(task.taskId)}
      style={{
        display: "block",
        width: "100%",
        textAlign: "left",
        padding: "var(--space-4) var(--space-5)",
        background: "var(--bg-2)",
        border: "1px solid var(--border)",
        borderRadius: "var(--radius-md)",
        cursor: "pointer",
        transition: "border-color 150ms var(--ease), background 150ms var(--ease)",
      }}
      onMouseEnter={(e) => {
        e.currentTarget.style.borderColor = "var(--border-2)";
        e.currentTarget.style.background = "var(--bg-3)";
      }}
      onMouseLeave={(e) => {
        e.currentTarget.style.borderColor = "var(--border)";
        e.currentTarget.style.background = "var(--bg-2)";
      }}
    >
      {/* Row 1: Task ID + Status + Attempt counter */}
      <div
        style={{
          display: "flex",
          alignItems: "center",
          gap: "var(--space-3)",
          marginBottom: "var(--space-2)",
        }}
      >
        <span
          className="mono"
          style={{ color: "var(--text-3)", fontSize: "11px", flexShrink: 0 }}
        >
          {task.taskId}
        </span>
        <StatusChip status={task.status} />
        <span
          className="mono"
          style={{ color: "var(--text-4)", fontSize: "10px", marginLeft: "auto" }}
        >
          {task.attemptCount}/{task.maxAttempts}
        </span>
      </div>

      {/* Row 2: Objective */}
      <p
        style={{
          color: "var(--text-1)",
          fontSize: "13px",
          lineHeight: 1.4,
          marginBottom: "var(--space-3)",
          overflow: "hidden",
          textOverflow: "ellipsis",
          whiteSpace: "nowrap",
        }}
      >
        {task.objective}
      </p>

      {/* Row 3: Metrics */}
      <div
        style={{
          display: "flex",
          alignItems: "center",
          gap: "var(--space-6)",
          flexWrap: "wrap",
        }}
      >
        <MetricBadge label="Agent" value={workerLabel} />
        {configLabel && <MetricBadge label="Mode" value={configLabel} />}
        <MetricBadge label="Latency" value={`${(totalLatency / 1000).toFixed(1)}s`} />
        <MetricBadge label="Cost" value={`$${totalCost.toFixed(4)}`} color="var(--accent)" />
        {lastAttempt?.errorTrace && (
          <span
            className="mono"
            style={{
              fontSize: "10px",
              color: "var(--status-failed)",
              overflow: "hidden",
              textOverflow: "ellipsis",
              whiteSpace: "nowrap",
              maxWidth: "300px",
            }}
          >
            {lastAttempt.errorTrace.split("\n")[0]}
          </span>
        )}
      </div>
    </button>
  );
}
