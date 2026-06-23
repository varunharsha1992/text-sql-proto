import type { Relationship } from "@/lib/types";

export default function RelationshipList({ relationships }: { relationships: Relationship[] }) {
  if (relationships.length === 0) return null;
  return (
    <div className="space-y-1.5">
      <div className="text-[10px] uppercase tracking-widest font-medium" style={{ color: "var(--text3)" }}>
        Relationships
      </div>
      <ul className="space-y-1">
        {relationships.map((r, i) => (
          <li key={i} className="text-[11px]" style={{ fontFamily: "'DM Mono', monospace", color: "var(--text2)" }}>
            {r.from_table}.{r.from_column} → {r.to_table}.{r.to_column}
            {r.confidence != null && (
              <span style={{ color: "var(--text3)" }}> ({Math.round(r.confidence * 100)}%)</span>
            )}
          </li>
        ))}
      </ul>
    </div>
  );
}
