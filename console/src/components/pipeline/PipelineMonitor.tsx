"use client";

import { TaskRow } from "./TaskRow";
import type { TaskExecutionLog } from "@/lib/types";

interface PipelineMonitorProps {
  tasks: TaskExecutionLog[];
  onInspect: (taskId: string) => void;
}

export function PipelineMonitor({ tasks, onInspect }: PipelineMonitorProps) {
  const activeTasks = tasks.filter(
    (t) => !["succeeded", "failed_terminal"].includes(t.task.status)
  );
  const completedTasks = tasks.filter((t) =>
    ["succeeded", "failed_terminal"].includes(t.task.status)
  );

  return (
    <div style={{ padding: "var(--space-6)", maxWidth: "900px" }}>
      {/* Header */}
      <div style={{ display: "flex", alignItems: "baseline", justifyContent: "space-between", marginBottom: "var(--space-6)" }}>
        <h1 className="display">Pipeline Monitor</h1>
        <div style={{ display: "flex", alignItems: "center", gap: "var(--space-4)" }}>
          <button 
            className="btn-secondary"
            style={{ fontSize: "11px", padding: "var(--space-2) var(--space-4)" }}
            onClick={async () => {
              try {
                const res = await fetch("/api/test/trigger", { method: "POST" });
                if (!res.ok) throw new Error("Failed to trigger simulation");
              } catch (err) {
                console.error(err);
              }
            }}
          >
            Simulate Agent Run
          </button>
          <span className="eyebrow" style={{ color: "var(--text-3)" }}>
            {activeTasks.length} active
          </span>
        </div>
      </div>

      {/* Active tasks */}
      {activeTasks.length > 0 && (
        <section style={{ marginBottom: "var(--space-8)" }}>
          <p
            className="eyebrow"
            style={{ marginBottom: "var(--space-3)", color: "var(--accent)" }}
          >
            Active
          </p>
          <div style={{ display: "flex", flexDirection: "column", gap: "var(--space-3)" }}>
            {activeTasks.map((log) => (
              <TaskRow key={log.task.taskId} log={log} onInspect={onInspect} />
            ))}
          </div>
        </section>
      )}

      {/* Completed tasks */}
      {completedTasks.length > 0 && (
        <section>
          <p
            className="eyebrow"
            style={{ marginBottom: "var(--space-3)", color: "var(--text-4)" }}
          >
            Completed
          </p>
          <div style={{ display: "flex", flexDirection: "column", gap: "var(--space-3)" }}>
            {completedTasks.map((log) => (
              <TaskRow key={log.task.taskId} log={log} onInspect={onInspect} />
            ))}
          </div>
        </section>
      )}

      {/* Empty state */}
      {tasks.length === 0 && (
        <div
          style={{
            padding: "var(--space-10)",
            textAlign: "center",
            color: "var(--text-4)",
          }}
        >
          <p style={{ fontFamily: "var(--font-display)", fontSize: "18px", marginBottom: "var(--space-2)" }}>
            No tasks in pipeline
          </p>
          <p style={{ fontSize: "12px" }}>
            Tasks will appear here when the orchestrator begins processing.
          </p>
        </div>
      )}
    </div>
  );
}
