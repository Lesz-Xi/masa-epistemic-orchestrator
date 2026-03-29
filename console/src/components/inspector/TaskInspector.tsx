"use client";

import { ArrowLeft } from "lucide-react";
import { StatusChip } from "@/components/primitives/StatusChip";
import { MetricBadge } from "@/components/primitives/MetricBadge";
import { ActionBar } from "@/components/primitives/ActionBar";
import { AttemptTimeline } from "./AttemptTimeline";
import type { TaskExecutionLog } from "@/lib/types";

interface TaskInspectorProps {
  log: TaskExecutionLog;
  onBack: () => void;
}

export function TaskInspector({ log, onBack }: TaskInspectorProps) {
  const { task, attempts } = log;
  const totalCost = attempts.reduce((sum, a) => sum + a.costUsd, 0);
  const totalLatency = attempts.reduce((sum, a) => sum + a.latencyMs, 0);
  const totalTokens = attempts.reduce((sum, a) => sum + a.tokensUsed, 0);

  const actions =
    task.status === "escalated"
      ? [
          { label: "Override & Approve", variant: "primary" as const, onClick: () => console.log("override", task.taskId) },
          { label: "Requeue", variant: "ghost" as const, onClick: () => console.log("requeue", task.taskId) },
          { label: "Dismiss", variant: "danger" as const, onClick: () => console.log("dismiss", task.taskId) },
        ]
      : task.status === "fixing" || task.status === "running"
        ? [
            { label: "Manual Fixer", variant: "ghost" as const, onClick: () => console.log("manual-fixer", task.taskId) },
          ]
        : [];

  return (
    <div style={{ padding: "var(--space-6)", maxWidth: "900px" }}>
      {/* Back button */}
      <button
        onClick={onBack}
        style={{
          display: "inline-flex",
          alignItems: "center",
          gap: "var(--space-2)",
          background: "none",
          border: "none",
          color: "var(--text-3)",
          fontFamily: "var(--font-mono)",
          fontSize: "11px",
          cursor: "pointer",
          marginBottom: "var(--space-5)",
          padding: 0,
        }}
      >
        <ArrowLeft size={12} />
        Back to pipeline
      </button>

      {/* Header */}
      <div
        style={{
          display: "flex",
          alignItems: "center",
          gap: "var(--space-3)",
          marginBottom: "var(--space-2)",
        }}
      >
        <span className="mono" style={{ color: "var(--text-3)", fontSize: "12px" }}>
          {task.taskId}
        </span>
        <StatusChip status={task.status} />
      </div>

      <h1
        className="display"
        style={{ marginBottom: "var(--space-4)", fontSize: "20px" }}
      >
        {task.objective}
      </h1>

      {/* Summary metrics */}
      <div
        style={{
          display: "flex",
          gap: "var(--space-8)",
          padding: "var(--space-4) 0",
          borderTop: "1px solid var(--border)",
          borderBottom: "1px solid var(--border)",
          marginBottom: "var(--space-6)",
        }}
      >
        <MetricBadge label="Attempts" value={`${task.attemptCount}/${task.maxAttempts}`} />
        <MetricBadge label="Total Time" value={`${(totalLatency / 1000).toFixed(1)}s`} />
        <MetricBadge label="Total Tokens" value={totalTokens.toLocaleString()} />
        <MetricBadge label="Total Cost" value={`$${totalCost.toFixed(4)}`} color="var(--accent)" />
      </div>

      {/* Attempt timeline */}
      <section style={{ marginBottom: "var(--space-6)" }}>
        <p className="eyebrow" style={{ marginBottom: "var(--space-4)" }}>
          Execution Timeline
        </p>
        <AttemptTimeline attempts={attempts} />
      </section>

      {/* Escalation banner */}
      {task.status === "escalated" && (
        <div
          style={{
            padding: "var(--space-4) var(--space-5)",
            background: "color-mix(in srgb, var(--status-escalated) 8%, var(--bg-2))",
            border: "1px solid color-mix(in srgb, var(--status-escalated) 25%, transparent)",
            borderRadius: "var(--radius-md)",
            marginBottom: "var(--space-4)",
          }}
        >
          <p
            className="eyebrow"
            style={{ color: "var(--status-escalated)", marginBottom: "var(--space-2)" }}
          >
            Escalated — Operator Action Required
          </p>
          <p style={{ fontSize: "12px", color: "var(--text-2)", lineHeight: 1.5 }}>
            All {task.maxAttempts} attempts exhausted. Review the timeline above and
            choose an action: approve the last output despite validation failure, requeue
            with a manual prompt, or dismiss.
          </p>
        </div>
      )}

      {/* Operator actions */}
      {actions.length > 0 && <ActionBar actions={actions} />}
    </div>
  );
}
