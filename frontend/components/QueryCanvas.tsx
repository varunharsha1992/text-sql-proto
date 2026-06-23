import type { CanvasResponse } from "@/lib/types";
import InsightCard from "@/components/InsightCards";
import ChartRenderer from "@/components/ChartRenderer";
import ResultsTable from "@/components/ResultsTable";

function LoadingSkeleton() {
  return (
    <div className="p-5 space-y-4">
      <div className="grid grid-cols-2 gap-3">
        {Array.from({ length: 2 }).map((_, i) => (
          <div key={i} className="h-48 rounded-lg bg-[var(--bg3)] animate-pulse" />
        ))}
      </div>
    </div>
  );
}

export default function QueryCanvas({
  canvas,
  loading,
}: {
  canvas: CanvasResponse | null;
  loading: boolean;
}) {
  if (loading && !canvas) return <LoadingSkeleton />;
  if (!canvas) {
    return (
      <div className="text-[13px] p-5" style={{ color: "var(--text3)" }}>
        Ask a question about your connected schema to see results here.
      </div>
    );
  }

  const stats = canvas.insights.filter((i) => i.type === "stat");
  const warnings = canvas.insights.filter((i) => i.type === "warning");
  const texts = canvas.insights.filter((i) => i.type === "text" || i.type === "badge");

  return (
    <div className="p-5 space-y-5">
      {stats.length > 0 && (
        <div className="grid grid-cols-2 lg:grid-cols-4 gap-3">
          {stats.map((s, i) => (
            <InsightCard key={i} item={s} />
          ))}
        </div>
      )}
      {warnings.map((w, i) => (
        <InsightCard key={`w-${i}`} item={w} />
      ))}
      {texts.map((t, i) => (
        <InsightCard key={`t-${i}`} item={t} />
      ))}
      {canvas.charts.length > 0 && (
        <div className="grid grid-cols-1 lg:grid-cols-2 gap-4">
          {canvas.charts.map((ch, i) => (
            <ChartRenderer key={i} spec={ch} />
          ))}
        </div>
      )}
      {canvas.table && <ResultsTable table={canvas.table} />}
    </div>
  );
}
