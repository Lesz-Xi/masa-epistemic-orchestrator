"use client";

import {
  Activity,
  AlertTriangle,
  Wrench,
  Beaker,
} from "lucide-react";
import type { ViewId } from "@/lib/types";

interface SidebarProps {
  activeView: ViewId;
  onNavigate: (view: ViewId) => void;
  taskCounts: {
    active: number;
    escalated: number;
  };
}

const NAV_ITEMS: { id: ViewId; label: string; icon: typeof Activity }[] = [
  { id: "pipeline", label: "Pipeline", icon: Activity },
  { id: "escalations", label: "Escalations", icon: AlertTriangle },
  { id: "tools", label: "Tool Runner", icon: Wrench },
];

export function Sidebar({ activeView, onNavigate, taskCounts }: SidebarProps) {
  return (
    <aside
      style={{
        background: "var(--sidebar-bg)",
        borderRight: "1px solid var(--border)",
        display: "flex",
        flexDirection: "column",
        height: "100vh",
        overflow: "hidden",
      }}
    >
      {/* Wordmark */}
      <div
        style={{
          height: "var(--topbar-h)",
          display: "flex",
          alignItems: "center",
          padding: "0 var(--space-5)",
          borderBottom: "1px solid var(--border)",
        }}
      >
        <Beaker
          size={14}
          style={{ color: "var(--accent)", marginRight: "var(--space-2)" }}
        />
        <span
          style={{
            fontFamily: "var(--font-display)",
            fontSize: "16px",
            color: "var(--text-1)",
            letterSpacing: "-0.01em",
          }}
        >
          MASA
        </span>
        <span
          className="eyebrow"
          style={{ marginLeft: "var(--space-2)", color: "var(--text-4)" }}
        >
          Console
        </span>
      </div>

      {/* Navigation */}
      <nav style={{ padding: "var(--space-3) var(--space-2)", flex: 1 }}>
        <p
          className="eyebrow"
          style={{ padding: "var(--space-2) var(--space-3)", marginBottom: "var(--space-1)" }}
        >
          Operator
        </p>
        {NAV_ITEMS.map((item) => {
          const isActive = activeView === item.id;
          const Icon = item.icon;
          const badge =
            item.id === "escalations" && taskCounts.escalated > 0
              ? taskCounts.escalated
              : null;

          return (
            <button
              key={item.id}
              onClick={() => onNavigate(item.id)}
              style={{
                display: "flex",
                alignItems: "center",
                width: "100%",
                padding: "var(--space-2) var(--space-3)",
                borderRadius: "var(--radius-sm)",
                border: "none",
                background: isActive ? "var(--bg-active)" : "transparent",
                color: isActive ? "var(--accent)" : "var(--text-2)",
                fontFamily: "var(--font-body)",
                fontSize: "13px",
                fontWeight: isActive ? 500 : 400,
                cursor: "pointer",
                transition: "background 150ms var(--ease), color 150ms var(--ease)",
                marginBottom: "var(--space-1)",
                textAlign: "left",
              }}
              onMouseEnter={(e) => {
                if (!isActive) e.currentTarget.style.background = "var(--bg-hover)";
              }}
              onMouseLeave={(e) => {
                if (!isActive) e.currentTarget.style.background = "transparent";
              }}
            >
              <Icon size={14} style={{ marginRight: "var(--space-3)", flexShrink: 0 }} />
              <span style={{ flex: 1 }}>{item.label}</span>
              {badge !== null && (
                <span
                  style={{
                    fontFamily: "var(--font-mono)",
                    fontSize: "10px",
                    fontWeight: 500,
                    background: "var(--status-escalated)",
                    color: "var(--bg)",
                    borderRadius: "var(--radius-sm)",
                    padding: "1px 6px",
                    lineHeight: "16px",
                  }}
                >
                  {badge}
                </span>
              )}
            </button>
          );
        })}
      </nav>

      {/* System status footer */}
      <div
        style={{
          padding: "var(--space-3) var(--space-5)",
          borderTop: "1px solid var(--border)",
        }}
      >
        <p className="eyebrow" style={{ marginBottom: "var(--space-1)" }}>
          Pipeline
        </p>
        <p className="mono" style={{ color: "var(--text-2)" }}>
          {taskCounts.active} active
        </p>
      </div>
    </aside>
  );
}
