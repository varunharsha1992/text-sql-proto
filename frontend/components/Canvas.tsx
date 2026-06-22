import type { CanvasResponse, InsightItem, ChartSpec, ProgressItem } from "@/lib/types";
import InsightCard from "@/components/InsightCards";
import ChartRenderer from "@/components/ChartRenderer";
import AgentProgress from "@/components/AgentProgress";
import DataDictionary from "@/components/DataDictionary";
import SemanticLayer from "@/components/SemanticLayer";

type StatusValue = "pending" | "running" | "done" | "error" | null | undefined;

function StatusBadge({ status }: { status: StatusValue }) {
  if (!status || status === "pending") {
    return (
      <span
        className="inline-flex items-center gap-1.5 px-2.5 py-1 rounded-full text-[10px] font-mono font-medium"
        style={{ background: "rgba(255,255,255,0.06)", color: "var(--text3)" }}
      >
        Waiting
      </span>
    );
  }

  if (status === "running") {
    return (
      <span
        className="inline-flex items-center gap-1.5 px-2.5 py-1 rounded-full text-[10px] font-mono font-medium"
        style={{ background: "rgba(99,179,237,0.12)", color: "var(--info, #63B3ED)" }}
      >
        <span
          className="w-1.5 h-1.5 rounded-full animate-pulse"
          style={{ background: "var(--info, #63B3ED)" }}
        />
        Analysing
      </span>
    );
  }

  if (status === "done") {
    return (
      <span
        className="inline-flex items-center gap-1.5 px-2.5 py-1 rounded-full text-[10px] font-mono font-medium"
        style={{ background: "rgba(110,231,183,0.12)", color: "var(--accent)" }}
      >
        Complete
      </span>
    );
  }

  // error
  return (
    <span
      className="inline-flex items-center gap-1.5 px-2.5 py-1 rounded-full text-[10px] font-mono font-medium"
      style={{ background: "rgba(248,113,113,0.12)", color: "var(--danger)" }}
    >
      Error
    </span>
  );
}

function LoadingSkeleton() {
  return (
    <div className="p-5 space-y-4">
      <div className="grid grid-cols-4 gap-3">
        {Array.from({ length: 4 }).map((_, i) => (
          <div
            key={i}
            className="h-20 rounded-lg bg-[var(--bg3)] animate-pulse"
          />
        ))}
      </div>
      <div className="grid grid-cols-2 gap-3">
        {Array.from({ length: 2 }).map((_, i) => (
          <div
            key={i}
            className="h-48 rounded-lg bg-[var(--bg3)] animate-pulse"
          />
        ))}
      </div>
    </div>
  );
}

interface CanvasProps {
  result: CanvasResponse | null;
  status?: "pending" | "running" | "done" | "error" | null;
  progress?: ProgressItem[] | null;
}

export default function Canvas({ result, status, progress }: CanvasProps) {
  const isLoading = status === "pending" || status === "running";

  const stats: InsightItem[] =
    result?.insights.filter((i) => i.type === "stat") ?? [];
  const warnings: InsightItem[] =
    result?.insights.filter((i) => i.type === "warning") ?? [];
  const charts: ChartSpec[] = result?.charts ?? [];

  // Pad stats to 4 columns
  const statPadCount = Math.max(0, 4 - stats.length);

  return (
    <div
      className="rounded-xl border overflow-hidden flex flex-col"
      style={{ borderColor: "var(--border)", background: "var(--bg2)" }}
    >
      {/* Header */}
      <div
        className="flex items-center justify-between px-5 py-3.5 border-b"
        style={{ borderColor: "var(--border)" }}
      >
        <h3
          className="text-[11px] uppercase tracking-widest font-medium"
          style={{ color: "var(--text3)" }}
        >
          Auto EDA — Analysis Canvas
        </h3>
        <StatusBadge status={status} />
      </div>

      {/* Body */}
      {isLoading && (
        <div className="p-5 space-y-4">
          {progress && progress.length > 0 && <AgentProgress items={progress} />}
          <LoadingSkeleton />
        </div>
      )}

      {!isLoading && result && (
        <div className="p-5 space-y-5">
          {/* Stat grid — always 4 columns */}
          <div className="grid grid-cols-4 gap-3">
            {stats.map((item, i) => (
              <InsightCard key={i} item={item} />
            ))}
            {Array.from({ length: statPadCount }).map((_, i) => (
              <div key={`pad-${i}`} />
            ))}
          </div>

          {/* Warnings section */}
          {warnings.length > 0 && (
            <div className="space-y-2">
              <div
                className="text-[10px] uppercase tracking-widest font-medium"
                style={{ color: "var(--text3)" }}
              >
                Data Quality
              </div>
              <div className="space-y-2">
                {warnings.map((item, i) => (
                  <InsightCard key={i} item={item} />
                ))}
              </div>
            </div>
          )}

          {/* Charts grid */}
          {charts.length > 0 && (
            <div className="grid grid-cols-2 gap-3">
              {charts.map((spec, i) => (
                <ChartRenderer key={i} spec={spec} />
              ))}
            </div>
          )}

          {/* Data dictionary */}
          {result.data_dictionary && result.data_dictionary.length > 0 && (
            <DataDictionary entries={result.data_dictionary} />
          )}

          {/* Semantic layer */}
          {result.semantic_layer && <SemanticLayer layer={result.semantic_layer} />}
        </div>
      )}

      {/* Empty state — status done but no result yet (edge case) */}
      {!isLoading && !result && (
        <div className="flex-1 flex items-center justify-center py-16 text-[12px]" style={{ color: "var(--text3)" }}>
          No analysis available.
        </div>
      )}
    </div>
  );
}
