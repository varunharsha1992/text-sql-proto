"use client";

import { useState } from "react";
import type { QueryMessage } from "@/lib/hooks";

const ROUTE_STYLE: Record<string, { label: string; bg: string; color: string }> = {
  sql: { label: "SQL", bg: "rgba(99,179,237,0.15)", color: "#63B3ED" },
  eda: { label: "EDA", bg: "rgba(167,139,250,0.15)", color: "#A78BFA" },
  both: { label: "Both", bg: "rgba(110,231,183,0.15)", color: "var(--accent)" },
};

function RouteBadge({ route, reason }: { route?: string; reason?: string | null }) {
  if (!route) return null;
  const s = ROUTE_STYLE[route] ?? ROUTE_STYLE.eda;
  return (
    <span
      title={reason ?? undefined}
      className="inline-block text-[9px] font-mono px-1.5 py-0.5 rounded ml-1"
      style={{ background: s.bg, color: s.color }}
    >
      {s.label}
    </span>
  );
}

export default function QueryChatPanel({
  messages,
  loading,
  onSend,
}: {
  messages: QueryMessage[];
  loading: boolean;
  onSend: (msg: string) => void;
}) {
  const [draft, setDraft] = useState("");

  const submit = () => {
    const t = draft.trim();
    if (!t || loading) return;
    onSend(t);
    setDraft("");
  };

  return (
    <div className="flex flex-col h-full">
      <div className="flex-1 min-h-0 overflow-y-auto space-y-3 p-1">
        {messages.map((m, i) => (
          <div key={i}>
            <div
              className="rounded-lg px-3 py-2 text-[13px] max-w-[90%]"
              style={{
                marginLeft: m.role === "user" ? "auto" : 0,
                background: m.role === "user" ? "var(--accent)" : "var(--bg3)",
                color: m.role === "user" ? "#000" : "var(--text)",
                whiteSpace: "pre-wrap",
              }}
            >
              {m.content}
              {m.role === "agent" && <RouteBadge route={m.route} reason={m.routeReason} />}
            </div>
            {m.role === "agent" && m.sqlQuery && (
              <details className="mt-1 text-[11px] max-w-[90%]">
                <summary className="cursor-pointer font-mono" style={{ color: "var(--text3)" }}>
                  SQL
                </summary>
                <pre
                  className="mt-1 p-2 rounded overflow-x-auto"
                  style={{ background: "var(--bg3)", color: "var(--text2)" }}
                >
                  {m.sqlQuery}
                </pre>
              </details>
            )}
          </div>
        ))}
        {loading && (
          <div className="text-[12px]" style={{ color: "var(--text3)" }}>
            Analysing…
          </div>
        )}
      </div>
      <div className="flex gap-2 pt-2">
        <input
          value={draft}
          onChange={(e) => setDraft(e.target.value)}
          onKeyDown={(e) => e.key === "Enter" && submit()}
          disabled={loading}
          placeholder="Ask about your data…"
          className="flex-1 rounded-lg px-3 py-2 text-[13px] outline-none"
          style={{ background: "var(--bg3)", border: "1px solid var(--border)", color: "var(--text)" }}
        />
        <button
          onClick={submit}
          disabled={loading}
          className="rounded-lg px-3 py-2 text-[13px] font-medium"
          style={{ background: "var(--bg4)", color: "var(--text)", opacity: loading ? 0.5 : 1 }}
        >
          Send
        </button>
      </div>
    </div>
  );
}
