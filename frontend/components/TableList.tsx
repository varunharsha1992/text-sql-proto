import type { UploadSummary, JobStatus } from "@/lib/types";

const STATUS_COLOR: Record<JobStatus, string> = {
  pending: "var(--text3)",
  running: "var(--info, #63B3ED)",
  done: "var(--accent)",
  error: "var(--danger)",
};

const STATUS_LABEL: Record<JobStatus, string> = {
  pending: "Queued",
  running: "Analysing",
  done: "Ready",
  error: "Error",
};

export default function TableList({
  uploads,
  selectedId,
  onSelect,
}: {
  uploads: UploadSummary[];
  selectedId: string | null;
  onSelect: (uploadId: string) => void;
}) {
  if (uploads.length === 0) return null;
  return (
    <div className="space-y-1.5">
      <div
        className="text-[10px] uppercase tracking-widest font-medium"
        style={{ color: "var(--text3)" }}
      >
        Tables in schema ({uploads.length})
      </div>
      <ul className="space-y-1">
        {uploads.map((u) => {
          const status = (u.status ?? "pending") as JobStatus;
          const selected = u.upload_id === selectedId;
          return (
            <li key={u.upload_id}>
              <button
                onClick={() => onSelect(u.upload_id)}
                className="w-full text-left rounded-lg px-3 py-2 transition-colors"
                style={{
                  background: selected ? "var(--bg4)" : "var(--bg3)",
                  border: `1px solid ${selected ? "var(--accent)" : "var(--border)"}`,
                }}
              >
                <div className="flex items-center justify-between gap-2">
                  <span
                    className="text-[12px] truncate"
                    style={{ fontFamily: "'DM Mono', monospace", color: "var(--text)" }}
                  >
                    {u.slug}
                  </span>
                  <span
                    className="text-[10px] shrink-0 px-1.5 py-0.5 rounded-full"
                    style={{ color: STATUS_COLOR[status] }}
                  >
                    {STATUS_LABEL[status]}
                  </span>
                </div>
                <div className="text-[10px] mt-0.5" style={{ color: "var(--text3)" }}>
                  {u.row_count != null ? `${u.row_count.toLocaleString()} rows` : "— rows"}
                  {"  ·  "}
                  {u.col_count != null ? `${u.col_count} cols` : "— cols"}
                </div>
              </button>
            </li>
          );
        })}
      </ul>
    </div>
  );
}
