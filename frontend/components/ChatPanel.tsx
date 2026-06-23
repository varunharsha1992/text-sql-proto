"use client";

import { useState } from "react";
import type { ChatMessage } from "@/lib/hooks";

export default function ChatPanel({
  messages,
  loading,
  complete,
  onSend,
  onMarkComplete,
}: {
  messages: ChatMessage[];
  loading: boolean;
  complete: boolean;
  onSend: (msg: string) => void;
  onMarkComplete: () => void;
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
          <div
            key={i}
            className="rounded-lg px-3 py-2 text-[13px] max-w-[90%]"
            style={{
              alignSelf: m.role === "user" ? "flex-end" : "flex-start",
              marginLeft: m.role === "user" ? "auto" : 0,
              background: m.role === "user" ? "var(--accent)" : "var(--bg3)",
              color: m.role === "user" ? "#000" : "var(--text)",
              whiteSpace: "pre-wrap",
            }}
          >
            {m.content}
          </div>
        ))}
        {loading && (
          <div className="text-[12px]" style={{ color: "var(--text3)" }}>
            Thinking…
          </div>
        )}
      </div>

      {complete && (
        <div className="text-[12px] mb-2 px-1" style={{ color: "var(--accent)" }}>
          Context saved — ready for queries.
        </div>
      )}

      <div className="flex gap-2 pt-2">
        <input
          value={draft}
          onChange={(e) => setDraft(e.target.value)}
          onKeyDown={(e) => e.key === "Enter" && submit()}
          disabled={loading}
          placeholder="Answer the agent…"
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
        <button
          onClick={onMarkComplete}
          disabled={loading || complete}
          className="rounded-lg px-3 py-2 text-[13px] font-medium"
          style={{
            background: "var(--accent)",
            color: "#000",
            opacity: loading || complete ? 0.5 : 1,
            cursor: loading || complete ? "not-allowed" : "pointer",
          }}
        >
          ✓ Mark Complete
        </button>
      </div>
    </div>
  );
}
