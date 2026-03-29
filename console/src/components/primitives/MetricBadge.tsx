interface MetricBadgeProps {
  label: string;
  value: string;
  color?: string;
}

export function MetricBadge({ label, value, color }: MetricBadgeProps) {
  return (
    <div
      style={{
        display: "inline-flex",
        alignItems: "baseline",
        gap: "var(--space-2)",
      }}
    >
      <span
        className="eyebrow"
        style={{ color: "var(--text-4)", fontSize: "9px" }}
      >
        {label}
      </span>
      <span
        className="mono"
        style={{
          fontSize: "12px",
          color: color || "var(--text-2)",
        }}
      >
        {value}
      </span>
    </div>
  );
}
