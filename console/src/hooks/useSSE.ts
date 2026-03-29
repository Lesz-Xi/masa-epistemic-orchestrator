import { useEffect } from "react";
import { useTaskStore } from "./useTaskStore";

export function useSSE() {
  const { upsertTask, addAttemptStart, addAttemptResult, escalateTask } = useTaskStore();

  useEffect(() => {
    const sse = new EventSource("/api/events");

    sse.addEventListener("task:status", (e) => {
      const data = JSON.parse(e.data);
      upsertTask(data.task_id, data.status, data.timestamp);
    });

    sse.addEventListener("attempt:start", (e) => {
      const data = JSON.parse(e.data);
      addAttemptStart(data.task_id, data.attempt_number, data.mode, data.timestamp);
    });

    sse.addEventListener("attempt:result", (e) => {
      const data = JSON.parse(e.data);
      addAttemptResult(
        data.task_id,
        data.attempt_number,
        data.passed,
        data.error_type,
        data.error_msg,
        data.timestamp
      );
    });

    sse.addEventListener("escalation", (e) => {
      const data = JSON.parse(e.data);
      // The payload must be the exact format expected by TracePayload
      escalateTask(data.task_id, data.payload);
    });

    sse.onopen = () => console.log("SSE Connected");
    sse.onerror = (err) => console.error("SSE Error:", err);

    return () => {
      sse.close();
    };
  }, [upsertTask, addAttemptStart, addAttemptResult, escalateTask]);
}
