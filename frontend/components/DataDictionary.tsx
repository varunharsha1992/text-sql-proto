import type { DataDictionaryEntry } from "@/lib/types";

export default function DataDictionary({
  entries,
}: {
  entries: DataDictionaryEntry[];
}) {
  if (!entries.length) return null;
  return (
    <div className="space-y-2">
      <div
        className="text-[10px] uppercase tracking-widest font-medium"
        style={{ color: "var(--text3)" }}
      >
        Data Dictionary
      </div>
      <div
        className="rounded-lg border overflow-hidden"
        style={{ borderColor: "var(--border)" }}
      >
        <table className="w-full text-[11px]" style={{ borderCollapse: "collapse" }}>
          <thead>
            <tr style={{ background: "var(--bg3)", color: "var(--text3)" }}>
              <th className="text-left px-3 py-1.5 font-medium">Column</th>
              <th className="text-left px-3 py-1.5 font-medium">Type</th>
              <th className="text-left px-3 py-1.5 font-medium">Description</th>
              <th className="text-right px-3 py-1.5 font-medium">Null %</th>
            </tr>
          </thead>
          <tbody>
            {entries.map((e) => (
              <tr key={e.column} style={{ borderTop: "1px solid var(--border)" }}>
                <td
                  className="px-3 py-1.5"
                  style={{ fontFamily: "'DM Mono', monospace", color: "var(--text)" }}
                >
                  {e.column}
                  {e.is_pii && (
                    <span
                      className="ml-1.5 px-1 rounded text-[9px]"
                      style={{ background: "rgba(248,113,113,0.12)", color: "var(--danger)" }}
                    >
                      PII
                    </span>
                  )}
                </td>
                <td className="px-3 py-1.5" style={{ color: "var(--text2)" }}>
                  {e.semantic_type}
                  {e.unit ? ` (${e.unit})` : ""}
                </td>
                <td className="px-3 py-1.5" style={{ color: "var(--text2)" }}>
                  {e.description}
                </td>
                <td
                  className="px-3 py-1.5 text-right"
                  style={{ color: e.null_pct > 5 ? "var(--accent3)" : "var(--text3)" }}
                >
                  {e.null_pct.toFixed(1)}%
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}
