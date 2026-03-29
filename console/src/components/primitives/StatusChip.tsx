import type { TaskStatus } from "@/lib/types";

const STATUS_CONFIG: Record<TaskStatus, { label: string; icon: string }> = {
  pending:         { label: "Pending",    icon: "○" },
  running:         { label: "Running",    icon: "●" },
  validating:      { label: "Validating", icon: "◎" },
  fixing:          { label: "Fixing",     icon: "◆" },
  succeeded:       { label: "Succeeded",  icon: "✓" },
  failed_terminal: { label: "Failed",     icon: "✗" },
  escalated:       { label: "Escalated",  icon: "▲" },
};

interface StatusChipProps {
  status: TaskStatus;
}

export function StatusChip({ status }: StatusChipProps) {
  const config = STATUS_CONFIG[status];
  const colorVar = `var(--status-${status === "failed_terminal" ? "failed" : status})`;

  return (
    <span
      style={{
        display: "inline-flex",
        alignItems: "center",
        gap: "var(--space-1)",
        fontFamily: "var(--font-mono)",
        fontSize: "10px",
        fontWeight: 500,
        letterSpacing: "0.08em",
        textTransform: "uppercase",
        color: colorVar,
        background: `color-mix(in srgb, ${colorVar} 12%, transparent)`,
        border: `1px solid color-mix(in srgb, ${colorVar} 25%, transparent)`,
        borderRadius: "var(--radius-sm)",
        padding: "2px 8px",
        lineHeight: "16px",
        whiteSpace: "nowrap",
      }}
    >
      <span style={{ fontSize: "8px" }}>{config.icon}</span>
      {config.label}
    </span>
  );
}
