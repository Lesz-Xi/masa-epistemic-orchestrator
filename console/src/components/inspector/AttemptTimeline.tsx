"use client";

import { MetricBadge } from "@/components/primitives/MetricBadge";
import { MonoBlock } from "@/components/primitives/MonoBlock";
import { FixerCard } from "./FixerCard";
import type { AttemptRecord } from "@/lib/types";

interface AttemptTimelineProps {
  attempts: AttemptRecord[];
}

export function AttemptTimeline({ attempts }: AttemptTimelineProps) {
  return (
    <div style={{ display: "flex", flexDirection: "column", gap: "var(--space-4)" }}>
      {attempts.map((attempt) => {
        const isExploration = attempt.configUsed.temperature > 0;
        const seedHex = attempt.configUsed.seed
          ? `0x${attempt.configUsed.seed.toString(16).toUpperCase()}`
          : null;

        return (
          <div key={attempt.attemptNumber}>
            {/* Attempt header line */}
            <div
              style={{
                display: "flex",
                alignItems: "center",
                gap: "var(--space-3)",
                marginBottom: "var(--space-3)",
              }}
            >
              {/* Timeline dot */}
              <div
                style={{
                  width: 8,
                  height: 8,
                  borderRadius: "50%",
                  background: attempt.validationPassed
                    ? "var(--status-succeeded)"
                    : "var(--status-failed)",
                  flexShrink: 0,
                }}
              />

              {/* Attempt label */}
              <span
                className="eyebrow"
                style={{
                  color: attempt.validationPassed
                    ? "var(--status-succeeded)"
                    : "var(--text-3)",
                }}
              >
                Attempt {attempt.attemptNumber}
              </span>

              {/* Horizontal rule */}
              <div
                style={{
                  flex: 1,
                  height: 1,
                  background: "var(--border)",
                }}
              />

              {/* Mode label */}
              <span
                className="mono"
                style={{ fontSize: "10px", color: "var(--text-4)" }}
              >
                {isExploration ? "EXPLORATION" : "FALLBACK"}
                {seedHex && ` (seed: ${seedHex})`}
              </span>
            </div>

            {/* Config row */}
            <div
              style={{
                display: "flex",
                gap: "var(--space-6)",
                marginBottom: "var(--space-3)",
                paddingLeft: "var(--space-5)",
              }}
            >
              <MetricBadge label="temp" value={String(attempt.configUsed.temperature)} />
              <MetricBadge label="top_p" value={String(attempt.configUsed.top_p)} />
              <MetricBadge label="top_k" value={String(attempt.configUsed.top_k)} />
              <MetricBadge
                label="Latency"
                value={`${(attempt.latencyMs / 1000).toFixed(1)}s`}
              />
              <MetricBadge
                label="Cost"
                value={`$${attempt.costUsd.toFixed(4)}`}
                color="var(--accent)"
              />
            </div>

            {/* Result */}
            <div style={{ paddingLeft: "var(--space-5)" }}>
              {attempt.validationPassed ? (
                <div
                  style={{
                    padding: "var(--space-3)",
                    background: "color-mix(in srgb, var(--status-succeeded) 5%, var(--bg-2))",
                    border: "1px solid color-mix(in srgb, var(--status-succeeded) 20%, transparent)",
                    borderRadius: "var(--radius-sm)",
                  }}
                >
                  <span
                    className="mono"
                    style={{ fontSize: "11px", color: "var(--status-succeeded)" }}
                  >
                    ✓ Validation passed
                  </span>
                </div>
              ) : (
                <>
                  {/* Error trace */}
                  {attempt.errorTrace && (
                    <div style={{ marginBottom: "var(--space-3)" }}>
                      <p className="eyebrow" style={{ marginBottom: "var(--space-1)" }}>
                        Error
                      </p>
                      <MonoBlock variant="error">{attempt.errorTrace}</MonoBlock>
                    </div>
                  )}

                  {/* Fixer card */}
                  {attempt.fixerDiagnostics && (
                    <FixerCard
                      failurePoint={attempt.fixerDiagnostics.failure_point}
                      correctionStrategy={attempt.fixerDiagnostics.correction_strategy}
                      rewrittenPrompt={attempt.rewrittenPrompt}
                    />
                  )}
                </>
              )}
            </div>
          </div>
        );
      })}
    </div>
  );
}
