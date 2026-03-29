import { MonoBlock } from "@/components/primitives/MonoBlock";

interface FixerCardProps {
  failurePoint: string;
  correctionStrategy: string;
  rewrittenPrompt?: string;
}

export function FixerCard({ failurePoint, correctionStrategy, rewrittenPrompt }: FixerCardProps) {
  return (
    <div
      style={{
        padding: "var(--space-4)",
        background: "color-mix(in srgb, var(--status-fixing) 5%, var(--bg-2))",
        border: "1px solid color-mix(in srgb, var(--status-fixing) 20%, transparent)",
        borderRadius: "var(--radius-md)",
      }}
    >
      <p
        className="eyebrow"
        style={{ color: "var(--status-fixing)", marginBottom: "var(--space-3)" }}
      >
        Fixer Intervention
      </p>

      <div style={{ marginBottom: "var(--space-3)" }}>
        <p className="eyebrow" style={{ marginBottom: "var(--space-1)" }}>Failure Point</p>
        <p style={{ fontSize: "12px", color: "var(--text-2)", lineHeight: 1.5 }}>
          {failurePoint}
        </p>
      </div>

      <div style={{ marginBottom: rewrittenPrompt ? "var(--space-3)" : 0 }}>
        <p className="eyebrow" style={{ marginBottom: "var(--space-1)" }}>Correction Strategy</p>
        <p style={{ fontSize: "12px", color: "var(--text-2)", lineHeight: 1.5 }}>
          {correctionStrategy}
        </p>
      </div>

      {rewrittenPrompt && (
        <div>
          <p className="eyebrow" style={{ marginBottom: "var(--space-1)" }}>Rewritten Prompt</p>
          <MonoBlock maxHeight="120px">{rewrittenPrompt}</MonoBlock>
        </div>
      )}
    </div>
  );
}
