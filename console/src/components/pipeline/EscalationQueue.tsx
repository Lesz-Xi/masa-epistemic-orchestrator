"use client";

import { TaskRow } from "./TaskRow";
import type { TaskExecutionLog } from "@/lib/types";

interface EscalationQueueProps {
  tasks: TaskExecutionLog[];
  onInspect: (taskId: string) => void;
}

export function EscalationQueue({ tasks, onInspect }: EscalationQueueProps) {
  const escalated = tasks.filter(
    (t) => t.task.status === "escalated" || t.task.status === "failed_terminal"
  );

  return (
    <div style={{ padding: "var(--space-6)", maxWidth: "900px" }}>
      <div
        style={{
          display: "flex",
          alignItems: "baseline",
          justifyContent: "space-between",
          marginBottom: "var(--space-6)",
        }}
      >
        <h1 className="display">Escalation Queue</h1>
        <span className="eyebrow" style={{ color: "var(--status-escalated)" }}>
          {escalated.length} pending review
        </span>
      </div>

      {escalated.length > 0 ? (
        <div style={{ display: "flex", flexDirection: "column", gap: "var(--space-3)" }}>
          {escalated.map((log) => (
            <TaskRow key={log.task.taskId} log={log} onInspect={onInspect} />
          ))}
        </div>
      ) : (
        <div
          style={{
            padding: "var(--space-10)",
            textAlign: "center",
            color: "var(--text-4)",
          }}
        >
          <p style={{ fontFamily: "var(--font-display)", fontSize: "18px", marginBottom: "var(--space-2)" }}>
            No escalations
          </p>
          <p style={{ fontSize: "12px" }}>
            Tasks that exhaust all retry attempts will appear here for operator review.
          </p>
        </div>
      )}
    </div>
  );
}
