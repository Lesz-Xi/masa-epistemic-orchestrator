import { create } from "zustand";
import type { TaskExecutionLog, TaskStatus, TracePayload, AttemptRecord } from "@/lib/types";

interface TaskStore {
  tasks: TaskExecutionLog[];
  setTasks: (tasks: TaskExecutionLog[]) => void;
  upsertTask: (taskId: string, status: TaskStatus, timestamp: string) => void;
  updateTaskStatus: (taskId: string, status: TaskStatus) => void;
  addAttemptStart: (taskId: string, attemptNumber: number, mode: string, timestamp: string) => void;
  addAttemptResult: (
    taskId: string,
    attemptNumber: number,
    passed: boolean,
    errorType?: string,
    errorMsg?: string,
    timestamp?: string
  ) => void;
  escalateTask: (taskId: string, payload: TracePayload) => void;
}

export const useTaskStore = create<TaskStore>((set) => ({
  tasks: [],

  setTasks: (tasks) => set({ tasks }),

  upsertTask: (taskId, status, timestamp) =>
    set((state) => {
      const existing = state.tasks.find((t) => t.task.taskId === taskId);
      if (existing) {
        return {
          tasks: state.tasks.map((t) =>
            t.task.taskId === taskId ? { ...t, task: { ...t.task, status } } : t
          ),
        };
      }
      // Create new skeleton task
      return {
        tasks: [
          ...state.tasks,
          {
            task: {
              taskId,
              objective: "Incoming Task...",
              requiredTools: [],
              outputSchemaName: "Unknown",
              status,
              attemptCount: 0,
              maxAttempts: 3,
              createdAt: timestamp || new Date().toISOString(),
            },
            attempts: [],
          },
        ],
      };
    }),

  updateTaskStatus: (taskId, status) =>
    set((state) => ({
      tasks: state.tasks.map((t) =>
        t.task.taskId === taskId ? { ...t, task: { ...t.task, status } } : t
      ),
    })),

  addAttemptStart: (taskId, attemptNumber, mode, timestamp) =>
    set((state) => ({
      tasks: state.tasks.map((t) => {
        if (t.task.taskId !== taskId) return t;
        
        const newAttempt: AttemptRecord = {
          attemptNumber,
          promptSent: "Waiting for output...",
          rawResponse: "",
          validationPassed: false,
          configUsed: {
            temperature: mode === "EXPLORATION" ? 0.7 : 0.0,
            top_p: 1.0,
            top_k: 40,
            response_format: { type: "json_object" },
          },
          timestamp: timestamp || new Date().toISOString(),
          latencyMs: 0,
          tokensUsed: 0,
          ttftMs: 0,
          totalMs: 0,
          tokensInput: 0,
          tokensOutput: 0,
          costUsd: 0,
        };

        return {
          ...t,
          task: {
            ...t.task,
            attemptCount: attemptNumber,
          },
          attempts: [...t.attempts, newAttempt],
        };
      }),
    })),

  addAttemptResult: (taskId, attemptNumber, passed, errorType, errorMsg, timestamp) =>
    set((state) => ({
      tasks: state.tasks.map((t) => {
        if (t.task.taskId !== taskId) return t;
        return {
          ...t,
          attempts: t.attempts.map((a) => {
            if (a.attemptNumber !== attemptNumber) return a;
            return {
              ...a,
              validationPassed: passed,
              errorTrace: errorMsg,
              fixerDiagnostics: errorType ? { failure_point: errorType, correction_strategy: "..." } : undefined,
            };
          }),
        };
      }),
    })),

  escalateTask: (taskId, payload) =>
    set((state) => ({
      tasks: state.tasks.map((t) =>
        t.task.taskId === taskId ? { ...t, escalationPayload: payload, task: { ...t.task, status: "escalated" } } : t
      ),
    })),
}));
