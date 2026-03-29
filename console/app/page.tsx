"use client";

import { useState, useMemo, useEffect } from "react";
import { Sidebar } from "@/components/shell/Sidebar";
import { Rail } from "@/components/shell/Rail";
import { PipelineMonitor } from "@/components/pipeline/PipelineMonitor";
import { EscalationQueue } from "@/components/pipeline/EscalationQueue";
import { TaskInspector } from "@/components/inspector/TaskInspector";
import { ToolRunnerPanel } from "@/components/tools/ToolRunnerPanel";
import { MOCK_TASKS } from "@/lib/mock-data";
import type { ViewId, AttemptRecord } from "@/lib/types";

import { useTaskStore } from "@/hooks/useTaskStore";
import { useSSE } from "@/hooks/useSSE";

export default function ConsolePage() {
  const [activeView, setActiveView] = useState<ViewId>("pipeline");
  const [inspectingTaskId, setInspectingTaskId] = useState<string | null>(null);

  const { tasks, setTasks } = useTaskStore();
  
  // Initialize with mock data once, then merge live updates
  useEffect(() => {
    if (tasks.length === 0) {
      setTasks(MOCK_TASKS);
    }
  }, [setTasks, tasks.length]);

  // Connect Server-Sent Events
  useSSE();

  // Derived state
  const taskCounts = useMemo(() => {
    const active = tasks.filter(
      (t) => !["succeeded", "failed_terminal", "escalated"].includes(t.task.status)
    ).length;
    const escalated = tasks.filter(
      (t) => t.task.status === "escalated" || t.task.status === "failed_terminal"
    ).length;
    return { active, escalated };
  }, [tasks]);

  const totalCost = useMemo(
    () =>
      tasks.reduce(
        (sum, log) =>
          sum + log.attempts.reduce((s, a) => s + (a.costUsd || 0), 0),
        0
      ),
    [tasks]
  );

  const recentAttempts = useMemo(() => {
    const all: (AttemptRecord & { taskId: string })[] = [];
    for (const log of tasks) {
      for (const attempt of log.attempts) {
        all.push({ ...attempt, taskId: log.task.taskId });
      }
    }
    return all.sort(
      (a, b) => new Date(b.timestamp).getTime() - new Date(a.timestamp).getTime()
    ).slice(0, 20);
  }, [tasks]);

  // Navigation
  const handleNavigate = (view: ViewId) => {
    setActiveView(view);
    setInspectingTaskId(null);
  };

  const handleInspect = (taskId: string) => {
    setInspectingTaskId(taskId);
  };

  const handleBack = () => {
    setInspectingTaskId(null);
  };

  // Find the log for inspection
  const inspectedLog = inspectingTaskId
    ? tasks.find((l) => l.task.taskId === inspectingTaskId)
    : null;

  // Render active view
  const renderMainContent = () => {
    // Task Inspector takes priority if a task is selected
    if (inspectedLog) {
      return <TaskInspector log={inspectedLog} onBack={handleBack} />;
    }

    switch (activeView) {
      case "pipeline":
        return <PipelineMonitor tasks={tasks} onInspect={handleInspect} />;
      case "escalations":
        return <EscalationQueue tasks={tasks} onInspect={handleInspect} />;
      case "tools":
        return <ToolRunnerPanel />;
      default:
        return <PipelineMonitor tasks={tasks} onInspect={handleInspect} />;
    }
  };

  return (
    <div className="shell">
      <Sidebar
        activeView={activeView}
        onNavigate={handleNavigate}
        taskCounts={taskCounts}
      />

      {/* Main workspace */}
      <main
        style={{
          overflowY: "auto",
          background: "var(--bg)",
        }}
      >
        {/* Topbar */}
        <div
          style={{
            height: "var(--topbar-h)",
            display: "flex",
            alignItems: "center",
            justifyContent: "space-between",
            padding: "0 var(--space-6)",
            borderBottom: "1px solid var(--border)",
            position: "sticky",
            top: 0,
            background: "var(--bg)",
            zIndex: 10,
          }}
        >
          <span className="eyebrow" style={{ color: "var(--text-3)" }}>
            {inspectedLog
              ? `Inspector — ${inspectedLog.task.taskId}`
              : activeView === "pipeline"
                ? "Pipeline Monitor"
                : activeView === "escalations"
                  ? "Escalation Queue"
                  : "Tool Runner"}
          </span>
          <span
            className="mono"
            style={{ fontSize: "10px", color: "var(--success-11)" }}
          >
            v2.0 — live connected
          </span>
        </div>

        {renderMainContent()}
      </main>

      <Rail recentAttempts={recentAttempts} totalCost={totalCost} />
    </div>
  );
}
