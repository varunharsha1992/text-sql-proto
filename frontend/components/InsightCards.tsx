import type { InsightItem, InsightColor } from "@/lib/types";

function resolveTextColor(color: InsightColor | null | undefined): string {
  if (color === "amber") return "var(--accent3)";
  if (color === "red") return "var(--danger)";
  if (color === "green") return "var(--accent)";
  return "var(--text)";
}

function StatCard({ item }: { item: InsightItem }) {
  return (
    <div className="bg-[var(--bg3)] border border-[var(--border)] rounded-lg p-3.5">
      {item.label && (
        <div className="text-[10px] uppercase tracking-widest text-[var(--text3)] mb-1">
          {item.label}
        </div>
      )}
      <div
        className="font-mono text-xl font-medium leading-none"
        style={{ color: resolveTextColor(item.color) }}
      >
        {item.value}
      </div>
    </div>
  );
}

function WarningCard({ item }: { item: InsightItem }) {
  return (
    <div
      className="border border-l-2 rounded-lg p-3 bg-[rgba(251,191,36,0.06)]"
      style={{
        borderLeftColor: "var(--accent3)",
        borderColor: "rgba(251,191,36,0.2)",
      }}
    >
      <div className="flex items-center gap-2">
        <span className="text-[var(--accent3)] text-sm">⚠</span>
        <span className="text-[12px] text-[var(--text2)]">{item.content}</span>
      </div>
    </div>
  );
}

function TextCard({ item }: { item: InsightItem }) {
  return (
    <div className="bg-[var(--bg3)] border border-[var(--border)] rounded-lg p-3">
      <p className="text-[12px] text-[var(--text2)] leading-relaxed">
        {item.content}
      </p>
    </div>
  );
}

function BadgeCard({ item }: { item: InsightItem }) {
  let bg: string;
  let textColor: string;

  if (item.color === "green") {
    bg = "rgba(110,231,183,0.12)";
    textColor = "var(--accent)";
  } else if (item.color === "amber") {
    bg = "rgba(251,191,36,0.12)";
    textColor = "var(--accent3)";
  } else if (item.color === "red") {
    bg = "rgba(248,113,113,0.12)";
    textColor = "var(--danger)";
  } else {
    bg = "rgba(255,255,255,0.05)";
    textColor = "var(--text3)";
  }

  return (
    <span
      className="inline-flex items-center px-2 py-0.5 rounded-full text-[10px] font-mono font-medium"
      style={{ backgroundColor: bg, color: textColor }}
    >
      {item.content}
    </span>
  );
}

export default function InsightCard({ item }: { item: InsightItem }) {
  switch (item.type) {
    case "stat":
      return <StatCard item={item} />;
    case "warning":
      return <WarningCard item={item} />;
    case "text":
      return <TextCard item={item} />;
    case "badge":
      return <BadgeCard item={item} />;
  }
}
