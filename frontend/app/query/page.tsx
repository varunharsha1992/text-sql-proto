"use client";

import { useQueryTurn } from "@/lib/hooks";
import QueryChatPanel from "@/components/QueryChatPanel";
import QueryCanvas from "@/components/QueryCanvas";

export default function QueryPage() {
  const { messages, canvas, loading, error, send } = useQueryTurn();

  return (
    <div className="flex-1 min-h-0 flex overflow-hidden" style={{ background: "var(--bg)" }}>
      <section
        className="w-[35%] shrink-0 flex flex-col p-4"
        style={{ borderRight: "1px solid var(--border)", background: "var(--bg2)" }}
      >
        {error && (
          <div className="text-[12px] mb-2" style={{ color: "var(--danger)" }}>
            {error}
          </div>
        )}
        <QueryChatPanel messages={messages} loading={loading} onSend={send} />
      </section>
      <main className="flex-1 min-h-0 overflow-y-auto">
        <QueryCanvas canvas={canvas} loading={loading} />
      </main>
    </div>
  );
}
