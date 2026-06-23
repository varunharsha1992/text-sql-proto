"use client";

import { useRouter } from "next/navigation";
import { useChatTurn, useUploadId } from "@/lib/hooks";
import ChatPanel from "@/components/ChatPanel";
import CatalogTable from "@/components/CatalogTable";
import RelationshipList from "@/components/RelationshipList";
import SchemaSemanticView from "@/components/SchemaSemanticView";

export default function ContextPage() {
  const router = useRouter();
  const { edaDone } = useUploadId();
  const { messages, catalog, semanticLayer, complete, loading, error, send, markComplete } =
    useChatTurn();

  return (
    <div className="flex-1 min-h-0 flex overflow-hidden" style={{ background: "var(--bg)" }}>
      {/* Left — chat (40%) */}
      <section
        className="w-2/5 shrink-0 flex flex-col p-4"
        style={{ borderRight: "1px solid var(--border)", background: "var(--bg2)" }}
      >
        {error && (
          <div className="text-[12px] mb-2" style={{ color: "var(--danger)" }}>
            {error}
          </div>
        )}
        <ChatPanel
          messages={messages}
          loading={loading}
          complete={complete}
          onSend={send}
          onMarkComplete={markComplete}
        />
        {edaDone && (
          <button
            type="button"
            onClick={() => router.push("/query")}
            className="mt-2 w-full rounded-lg px-3 py-2 text-[13px] font-medium"
            style={{ background: "var(--accent)", color: "#000" }}
          >
            Continue to Query Canvas →
          </button>
        )}
      </section>

      {/* Right — schema (60%) */}
      <main className="flex-1 min-h-0 overflow-y-auto p-5 space-y-5">
        {semanticLayer && semanticLayer.relationships.length > 0 && (
          <RelationshipList relationships={semanticLayer.relationships} />
        )}
        <CatalogTable rows={catalog} />
        {semanticLayer && <SchemaSemanticView layer={semanticLayer} />}
        {catalog.length === 0 && (
          <div className="text-[12px]" style={{ color: "var(--text3)" }}>
            No schema yet. Upload CSVs on the Upload screen first.
          </div>
        )}
      </main>
    </div>
  );
}
