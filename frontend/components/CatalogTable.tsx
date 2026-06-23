import type { CatalogRow } from "@/lib/types";

export default function CatalogTable({ rows }: { rows: CatalogRow[] }) {
  if (rows.length === 0) return null;
  const byTable = new Map<string, CatalogRow[]>();
  for (const r of rows) {
    const arr = byTable.get(r.slug) ?? [];
    arr.push(r);
    byTable.set(r.slug, arr);
  }
  return (
    <div className="space-y-4">
      {Array.from(byTable.entries()).map(([slug, cols]) => (
        <div key={slug} className="space-y-1.5">
          <div
            className="text-[11px] font-medium"
            style={{ fontFamily: "'DM Mono', monospace", color: "var(--accent)" }}
          >
            {slug}
          </div>
          <div className="rounded-lg border overflow-hidden" style={{ borderColor: "var(--border)" }}>
            <table className="w-full text-[11px]" style={{ borderCollapse: "collapse" }}>
              <thead>
                <tr style={{ background: "var(--bg3)", color: "var(--text3)" }}>
                  <th className="text-left px-2 py-1 font-medium">Column</th>
                  <th className="text-left px-2 py-1 font-medium">Role</th>
                  <th className="text-left px-2 py-1 font-medium">Description / context</th>
                  <th className="text-left px-2 py-1 font-medium">Key</th>
                </tr>
              </thead>
              <tbody>
                {cols.map((c) => (
                  <tr key={`${c.upload_id}:${c.column_name}`} style={{ borderTop: "1px solid var(--border)" }}>
                    <td className="px-2 py-1" style={{ fontFamily: "'DM Mono', monospace", color: "var(--text)" }}>
                      {c.column_name}
                      {c.is_pii && (
                        <span className="ml-1 px-1 rounded text-[9px]" style={{ background: "rgba(248,113,113,0.12)", color: "var(--danger)" }}>
                          PII
                        </span>
                      )}
                    </td>
                    <td className="px-2 py-1" style={{ color: "var(--text2)" }}>{c.semantic_role ?? "—"}</td>
                    <td className="px-2 py-1" style={{ color: "var(--text2)" }}>
                      {c.business_context || c.description || "—"}
                    </td>
                    <td className="px-2 py-1" style={{ color: "var(--text3)" }}>
                      {c.is_primary_key ? "PK" : c.is_foreign_key ? `FK → ${c.foreign_key_ref ?? "?"}` : "—"}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      ))}
    </div>
  );
}
