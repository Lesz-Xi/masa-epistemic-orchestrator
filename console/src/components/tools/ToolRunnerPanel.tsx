"use client";

import { useState } from "react";
import { MonoBlock } from "@/components/primitives/MonoBlock";

export function ToolRunnerPanel() {
  const [query, setQuery] = useState("");
  const [epistemicFilter, setEpistemicFilter] = useState("peer_reviewed_only");
  const [chunkOffset, setChunkOffset] = useState(0);
  const [yearRange, setYearRange] = useState("");
  const [result, setResult] = useState<string | null>(null);
  const [isRunning, setIsRunning] = useState(false);

  const handleRun = () => {
    // Stub — will be replaced with actual MCP tool call
    setIsRunning(true);
    setTimeout(() => {
      setResult(
        `============================================================\n` +
        `MASA Literature Search — Results\n` +
        `============================================================\n` +
        `Query: "${query}"\n` +
        `Epistemic Filter: ${epistemicFilter}\n` +
        `Upstream Hits: 42\n` +
        `Eligible Papers (post-filter): 38\n` +
        `Showing: 1–3 of 38\n` +
        `API Latency: 340 ms\n` +
        `------------------------------------------------------------\n\n` +
        `[Reference ID: 1]\n` +
        `  Title: (Mock result — connect to MCP server for live data)\n` +
        `  Authors: —\n` +
        `  Year: 2024\n` +
        `  Citations: —\n` +
        `  Semantic Scholar ID: mock-paper-1\n\n` +
        `[PAGINATION] 35 more paper(s) available. To see the next page, call this tool again with chunk_offset=3.\n\n` +
        `CITATION CONTRACT: You MUST cite papers using their [Reference ID: N].`
      );
      setIsRunning(false);
    }, 800);
  };

  return (
    <div style={{ padding: "var(--space-6)", maxWidth: "900px" }}>
      <h1 className="display" style={{ marginBottom: "var(--space-6)" }}>
        Tool Runner
      </h1>

      <p
        className="eyebrow"
        style={{ marginBottom: "var(--space-3)", color: "var(--accent)" }}
      >
        literature_search
      </p>

      {/* Form */}
      <div
        style={{
          display: "grid",
          gap: "var(--space-4)",
          marginBottom: "var(--space-5)",
        }}
      >
        {/* Query */}
        <div>
          <label className="eyebrow" style={{ display: "block", marginBottom: "var(--space-1)" }}>
            Query
          </label>
          <input
            type="text"
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            placeholder="e.g., BRCA1 causal mechanisms in breast cancer"
            style={{
              width: "100%",
              padding: "var(--space-2) var(--space-3)",
              fontFamily: "var(--font-body)",
              fontSize: "13px",
              background: "var(--bg-2)",
              border: "1px solid var(--border)",
              borderRadius: "var(--radius-sm)",
              color: "var(--text-1)",
              outline: "none",
            }}
            onFocus={(e) => (e.currentTarget.style.borderColor = "var(--accent)")}
            onBlur={(e) => (e.currentTarget.style.borderColor = "var(--border)")}
          />
        </div>

        {/* Row: filter + offset + year */}
        <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr 1fr", gap: "var(--space-3)" }}>
          <div>
            <label className="eyebrow" style={{ display: "block", marginBottom: "var(--space-1)" }}>
              Epistemic Filter
            </label>
            <select
              value={epistemicFilter}
              onChange={(e) => setEpistemicFilter(e.target.value)}
              style={{
                width: "100%",
                padding: "var(--space-2) var(--space-3)",
                fontFamily: "var(--font-mono)",
                fontSize: "11px",
                background: "var(--bg-2)",
                border: "1px solid var(--border)",
                borderRadius: "var(--radius-sm)",
                color: "var(--text-2)",
                outline: "none",
              }}
            >
              <option value="peer_reviewed_only">peer_reviewed_only</option>
              <option value="all">all</option>
            </select>
          </div>

          <div>
            <label className="eyebrow" style={{ display: "block", marginBottom: "var(--space-1)" }}>
              Chunk Offset
            </label>
            <input
              type="number"
              min={0}
              value={chunkOffset}
              onChange={(e) => setChunkOffset(Number(e.target.value))}
              style={{
                width: "100%",
                padding: "var(--space-2) var(--space-3)",
                fontFamily: "var(--font-mono)",
                fontSize: "11px",
                background: "var(--bg-2)",
                border: "1px solid var(--border)",
                borderRadius: "var(--radius-sm)",
                color: "var(--text-2)",
                outline: "none",
              }}
            />
          </div>

          <div>
            <label className="eyebrow" style={{ display: "block", marginBottom: "var(--space-1)" }}>
              Year Range
            </label>
            <input
              type="text"
              value={yearRange}
              onChange={(e) => setYearRange(e.target.value)}
              placeholder="e.g., 2020-2025"
              style={{
                width: "100%",
                padding: "var(--space-2) var(--space-3)",
                fontFamily: "var(--font-mono)",
                fontSize: "11px",
                background: "var(--bg-2)",
                border: "1px solid var(--border)",
                borderRadius: "var(--radius-sm)",
                color: "var(--text-2)",
                outline: "none",
              }}
            />
          </div>
        </div>

        {/* Run button */}
        <div>
          <button
            onClick={handleRun}
            disabled={!query.trim() || isRunning}
            style={{
              fontFamily: "var(--font-mono)",
              fontSize: "10px",
              fontWeight: 500,
              letterSpacing: "0.08em",
              textTransform: "uppercase",
              padding: "var(--space-2) var(--space-6)",
              borderRadius: "var(--radius-sm)",
              border: "none",
              background: query.trim() ? "var(--accent)" : "var(--bg-4)",
              color: query.trim() ? "var(--bg)" : "var(--text-4)",
              cursor: query.trim() ? "pointer" : "not-allowed",
              transition: "background 150ms var(--ease)",
            }}
          >
            {isRunning ? "Running…" : "Execute Tool"}
          </button>
        </div>
      </div>

      {/* Result */}
      {result && (
        <div>
          <p className="eyebrow" style={{ marginBottom: "var(--space-2)" }}>
            Tool Response
          </p>
          <MonoBlock maxHeight="500px">{result}</MonoBlock>
        </div>
      )}
    </div>
  );
}
