import type { ProgressItem } from "@/lib/types";

const ICON: Record<ProgressItem["status"], string> = {
  completed: "✓",
  in_progress: "◐",
  pending: "○",
};

const COLOR: Record<ProgressItem["status"], string> = {
  completed: "var(--accent)",
  in_progress: "var(--info, #63B3ED)",
  pending: "var(--text3)",
};

export default function AgentProgress({ items }: { items: ProgressItem[] }) {
  if (!items.length) return null;
  return (
    <div className="space-y-1.5">
      <div
        className="text-[10px] uppercase tracking-widest font-medium"
        style={{ color: "var(--text3)" }}
      >
        Agent plan
      </div>
      <ul className="space-y-1">
        {items.map((it, i) => (
          <li key={i} className="flex items-center gap-2 text-[12px]">
            <span style={{ color: COLOR[it.status] }}>{ICON[it.status]}</span>
            <span
              style={{
                color: it.status === "completed" ? "var(--text3)" : "var(--text2)",
                textDecoration: it.status === "completed" ? "line-through" : "none",
              }}
            >
              {it.text}
            </span>
          </li>
        ))}
      </ul>
    </div>
  );
}
