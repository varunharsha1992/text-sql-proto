import type { SchemaSemanticLayer } from "@/lib/types";

export default function SchemaSemanticView({ layer }: { layer: SchemaSemanticLayer }) {
  return (
    <div className="space-y-3">
      <div className="text-[10px] uppercase tracking-widest font-medium" style={{ color: "var(--text3)" }}>
        Schema Semantic Layer
      </div>
      <div className="grid grid-cols-2 gap-3">
        <div>
          <div className="text-[11px] mb-1" style={{ color: "var(--text3)" }}>Measures</div>
          <ul className="space-y-1">
            {layer.measures.map((m, i) => (
              <li key={i} className="text-[11px]" style={{ color: "var(--text2)" }}>
                <span style={{ color: "var(--accent)" }}>{m.aggregation}</span>(
                <span style={{ fontFamily: "'DM Mono', monospace" }}>{m.table}.{m.column}</span>) — {m.name}
              </li>
            ))}
          </ul>
        </div>
        <div>
          <div className="text-[11px] mb-1" style={{ color: "var(--text3)" }}>Dimensions</div>
          <ul className="space-y-1">
            {layer.dimensions.map((d, i) => (
              <li key={i} className="text-[11px]" style={{ color: "var(--text2)" }}>
                <span style={{ fontFamily: "'DM Mono', monospace" }}>{d.table}.{d.column}</span> — {d.name}
              </li>
            ))}
          </ul>
        </div>
      </div>
      {layer.suggested_questions.length > 0 && (
        <div>
          <div className="text-[11px] mb-1" style={{ color: "var(--text3)" }}>Suggested questions</div>
          <div className="flex flex-wrap gap-1.5">
            {layer.suggested_questions.map((q, i) => (
              <span key={i} className="text-[11px] px-2 py-1 rounded-full" style={{ background: "var(--bg3)", color: "var(--text2)" }}>
                {q}
              </span>
            ))}
          </div>
        </div>
      )}
    </div>
  );
}
