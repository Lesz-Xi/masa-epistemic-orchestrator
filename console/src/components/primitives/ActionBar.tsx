interface Action {
  label: string;
  onClick: () => void;
  variant?: "primary" | "ghost" | "danger";
}

interface ActionBarProps {
  actions: Action[];
}

export function ActionBar({ actions }: ActionBarProps) {
  return (
    <div
      style={{
        display: "flex",
        justifyContent: "flex-end",
        gap: "var(--space-2)",
        padding: "var(--space-3) 0",
      }}
    >
      {actions.map((action) => {
        const isPrimary = action.variant === "primary";
        const isDanger = action.variant === "danger";

        return (
          <button
            key={action.label}
            onClick={action.onClick}
            style={{
              fontFamily: "var(--font-mono)",
              fontSize: "10px",
              fontWeight: 500,
              letterSpacing: "0.08em",
              textTransform: "uppercase",
              padding: "var(--space-2) var(--space-4)",
              borderRadius: "var(--radius-sm)",
              border: isPrimary
                ? "none"
                : `1px solid ${isDanger ? "var(--status-failed)" : "var(--border)"}`,
              background: isPrimary ? "var(--text-1)" : "transparent",
              color: isPrimary
                ? "var(--bg)"
                : isDanger
                  ? "var(--status-failed)"
                  : "var(--text-3)",
              cursor: "pointer",
              transition: "background 150ms var(--ease), color 150ms var(--ease)",
            }}
          >
            {action.label}
          </button>
        );
      })}
    </div>
  );
}
