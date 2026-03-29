"use client";

import type { AttemptRecord } from "@/lib/types";

interface RailProps {
  recentAttempts: (AttemptRecord & { taskId: string })[];
  totalCost: number;
}

export function Rail({ recentAttempts, totalCost }: RailProps) {
  return (
    <aside
      style={{
        background: "var(--bg-2)",
        borderLeft: "1px solid var(--border)",
        display: "flex",
        flexDirection: "column",
        height: "100vh",
        overflow: "hidden",
      }}
    >
      {/* Rail header */}
      <div
        style={{
          height: "var(--topbar-h)",
          display: "flex",
          alignItems: "center",
          justifyContent: "space-between",
          padding: "0 var(--space-5)",
          borderBottom: "1px solid var(--border)",
        }}
      >
        <span className="eyebrow">Live Trace</span>
        <span
          className="mono"
          style={{ color: "var(--accent)", fontSize: "11px" }}
        >
          ${totalCost.toFixed(4)}
        </span>
      </div>

      {/* Trace feed */}
      <div
        style={{
          flex: 1,
          overflowY: "auto",
          padding: "var(--space-3)",
        }}
      >
        {recentAttempts.length === 0 && (
          <p
            style={{
              color: "var(--text-4)",
              fontSize: "12px",
              padding: "var(--space-4)",
              textAlign: "center",
            }}
          >
            No activity yet
          </p>
        )}
        {recentAttempts.map((attempt, i) => (
          <div
            key={`${attempt.taskId}-${attempt.attemptNumber}-${i}`}
            style={{
              padding: "var(--space-3)",
              marginBottom: "var(--space-2)",
              borderRadius: "var(--radius-sm)",
              background: "var(--bg-3)",
              border: "1px solid var(--border)",
            }}
          >
            <div
              style={{
                display: "flex",
                justifyContent: "space-between",
                marginBottom: "var(--space-1)",
              }}
            >
              <span
                className="mono"
                style={{ color: "var(--text-2)", fontSize: "11px" }}
              >
                {attempt.taskId}
              </span>
              <span
                className="mono"
                style={{
                  fontSize: "10px",
                  color: attempt.validationPassed
                    ? "var(--status-succeeded)"
                    : "var(--status-failed)",
                }}
              >
                {attempt.validationPassed ? "PASS" : "FAIL"}
              </span>
            </div>
            <div
              style={{
                display: "flex",
                gap: "var(--space-4)",
                fontSize: "11px",
                color: "var(--text-3)",
                fontFamily: "var(--font-mono)",
              }}
            >
              <span>{attempt.latencyMs.toFixed(0)}ms</span>
              <span>{attempt.tokensUsed}tok</span>
              <span>${attempt.costUsd.toFixed(4)}</span>
            </div>
            {attempt.errorTrace && (
              <p
                style={{
                  marginTop: "var(--space-2)",
                  fontSize: "11px",
                  color: "var(--status-failed)",
                  fontFamily: "var(--font-mono)",
                  whiteSpace: "nowrap",
                  overflow: "hidden",
                  textOverflow: "ellipsis",
                }}
              >
                {attempt.errorTrace.split("\n")[0]}
              </p>
            )}
          </div>
        ))}
      </div>

      {/* Cost meter */}
      <div
        style={{
          padding: "var(--space-4) var(--space-5)",
          borderTop: "1px solid var(--border)",
        }}
      >
        <p className="eyebrow" style={{ marginBottom: "var(--space-1)" }}>
          Session Cost
        </p>
        <p
          style={{
            fontFamily: "var(--font-mono)",
            fontSize: "18px",
            fontWeight: 500,
            color: "var(--text-1)",
          }}
        >
          ${totalCost.toFixed(4)}
        </p>
      </div>
    </aside>
  );
}
