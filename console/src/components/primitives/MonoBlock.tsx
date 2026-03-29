interface MonoBlockProps {
  children: string;
  variant?: "default" | "error";
  maxHeight?: string;
}

export function MonoBlock({ children, variant = "default", maxHeight = "200px" }: MonoBlockProps) {
  const isError = variant === "error";

  return (
    <pre
      style={{
        fontFamily: "var(--font-mono)",
        fontSize: "11px",
        lineHeight: 1.6,
        padding: "var(--space-3)",
        borderRadius: "var(--radius-sm)",
        border: `1px solid ${isError ? "rgba(217, 106, 93, 0.2)" : "var(--border)"}`,
        background: isError ? "rgba(217, 106, 93, 0.05)" : "var(--bg)",
        color: isError ? "var(--status-failed)" : "var(--text-2)",
        overflow: "auto",
        maxHeight,
        whiteSpace: "pre-wrap",
        wordBreak: "break-word",
      }}
    >
      {children}
    </pre>
  );
}
