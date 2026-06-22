"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { useRouter } from "next/navigation";
import { uploadFile } from "@/lib/api";
import { useUploadId, usePolling } from "@/lib/hooks";
import Canvas from "@/components/Canvas";

// ─── Helpers ─────────────────────────────────────────────────────────────────

function formatBytes(bytes: number): string {
  if (bytes >= 1_048_576) return `${(bytes / 1_048_576).toFixed(1)} MB`;
  if (bytes >= 1_024) return `${(bytes / 1_024).toFixed(0)} KB`;
  return `${bytes} B`;
}

function parseNullPct(content: string): { column: string; pct: number } | null {
  const match = content.match(/^(.+?):\s*([\d.]+)%\s*null/i);
  if (!match) return null;
  return { column: match[1].trim(), pct: parseFloat(match[2]) };
}

// ─── Animated dot ────────────────────────────────────────────────────────────

function PulsingDot() {
  return (
    <span className="inline-flex gap-0.5 items-center ml-1">
      {[0, 1, 2].map((i) => (
        <span
          key={i}
          className="w-1 h-1 rounded-full animate-bounce"
          style={{
            background: "var(--text3)",
            animationDelay: `${i * 150}ms`,
            animationDuration: "900ms",
          }}
        />
      ))}
    </span>
  );
}

// ─── Main page ───────────────────────────────────────────────────────────────

export default function UploadPage() {
  const fileInputRef = useRef<HTMLInputElement>(null);
  const [file, setFile] = useState<File | null>(null);
  const [isDragging, setIsDragging] = useState(false);
  const [uploadError, setUploadError] = useState<string | null>(null);
  const [isUploading, setIsUploading] = useState(false);

  const { jobId, setUpload, setEdaDone, clear } = useUploadId();
  const { status, result, error, progress } = usePolling(jobId);

  // Row/column counts come back in the analysis result's stat cards (FR-004).
  const statValue = (label: string): string | null =>
    result?.insights.find(
      (i) => i.type === "stat" && i.label?.toLowerCase() === label
    )?.value ?? null;
  const rowsDisplay = statValue("rows") ?? "—";
  const colsDisplay = statValue("columns") ?? "—";

  useEffect(() => {
    if (status === "done") setEdaDone();
  }, [status, setEdaDone]);

  const handleFileSelect = useCallback(
    async (f: File) => {
      setFile(f);
      setUploadError(null);
      setIsUploading(true);
      try {
        const res = await uploadFile(f);
        setUpload(res.upload_id, res.job_id, res.slug);
      } catch (e) {
        setUploadError(e instanceof Error ? e.message : "Upload failed");
      } finally {
        setIsUploading(false);
      }
    },
    [setUpload]
  );

  // Drag and drop handlers
  const onDragOver = useCallback((e: React.DragEvent) => {
    e.preventDefault();
    setIsDragging(true);
  }, []);

  const onDragLeave = useCallback((e: React.DragEvent) => {
    e.preventDefault();
    setIsDragging(false);
  }, []);

  const onDrop = useCallback(
    (e: React.DragEvent) => {
      e.preventDefault();
      setIsDragging(false);
      const dropped = e.dataTransfer.files[0];
      if (dropped) handleFileSelect(dropped);
    },
    [handleFileSelect]
  );

  const onFileInputChange = useCallback(
    (e: React.ChangeEvent<HTMLInputElement>) => {
      const selected = e.target.files?.[0];
      if (selected) handleFileSelect(selected);
    },
    [handleFileSelect]
  );

  // Parse quality rows from warnings
  const qualityRows = (result?.insights ?? [])
    .filter((ins) => ins.type === "warning" && ins.content)
    .map((ins) => parseNullPct(ins.content!))
    .filter((item): item is { column: string; pct: number } => item !== null)
    .slice(0, 5);

  const router = useRouter();
  const canContinue = status === "done";
  const showAnalysing = status === "running" || (isUploading === false && jobId && status === "pending");

  const handleReset = useCallback(() => {
    setFile(null);
    setUploadError(null);
    setIsUploading(false);
    clear(); // drop upload/job ids so polling stops and the errored job is forgotten
    if (fileInputRef.current) fileInputRef.current.value = "";
  }, [clear]);

  return (
    <div
      className="flex h-screen overflow-hidden"
      style={{ background: "var(--bg)" }}
    >
      {/* ── Left panel ── */}
      <aside
        className="flex flex-col w-[360px] shrink-0 overflow-y-auto"
        style={{
          background: "var(--bg2)",
          borderRight: "1px solid var(--border)",
        }}
      >
        {/* Upload zone */}
        <div className="p-4">
          <div
            role="button"
            tabIndex={0}
            className="flex flex-col items-center justify-center gap-2 rounded-xl p-8 cursor-pointer transition-colors duration-150 select-none"
            style={{
              border: `1.5px dashed ${isDragging ? "var(--accent)" : "var(--border2)"}`,
              background: isDragging ? "rgba(110,231,183,0.04)" : "transparent",
            }}
            onClick={() => fileInputRef.current?.click()}
            onKeyDown={(e) => e.key === "Enter" && fileInputRef.current?.click()}
            onDragOver={onDragOver}
            onDragLeave={onDragLeave}
            onDrop={onDrop}
          >
            <span className="text-3xl">📊</span>
            <p className="font-medium" style={{ color: "var(--text)" }}>
              Drop your CSV here
            </p>
            <p className="text-[12px]" style={{ color: "var(--text3)" }}>
              or click to browse · max 50MB
            </p>
          </div>
          <input
            ref={fileInputRef}
            type="file"
            accept=".csv"
            className="hidden"
            onChange={onFileInputChange}
          />
        </div>

        {/* File info card */}
        {file && (
          <div
            className="mx-4 mb-4 rounded-lg p-3"
            style={{
              background: "var(--bg3)",
              border: "1px solid var(--border)",
            }}
          >
            <p
              className="text-[12px] font-medium mb-3 truncate"
              style={{
                fontFamily: "'DM Mono', monospace",
                color: "var(--accent)",
              }}
            >
              {file.name}
            </p>
            <div className="grid grid-cols-2 gap-x-4 gap-y-1.5">
              {[
                { label: "Rows", value: rowsDisplay },
                { label: "Columns", value: colsDisplay },
                { label: "Size", value: formatBytes(file.size) },
                { label: "Encoding", value: "UTF-8" },
              ].map(({ label, value }) => (
                <div key={label} className="flex justify-between">
                  <span style={{ color: "var(--text3)" }} className="text-[11px]">
                    {label}
                  </span>
                  <span
                    style={{ color: "var(--text2)" }}
                    className="text-[11px] font-medium"
                  >
                    {value}
                  </span>
                </div>
              ))}
            </div>
          </div>
        )}

        {/* Upload / analysis status */}
        {(isUploading || (jobId && (status === "running" || status === "pending"))) && (
          <div className="mx-4 mb-3 flex items-center gap-1.5">
            <span
              className="text-[12px]"
              style={{ color: "var(--text2)" }}
            >
              {isUploading ? "Uploading…" : "Analysing…"}
            </span>
            {!isUploading && <PulsingDot />}
          </div>
        )}

        {/* Upload / agent error card with Try Again */}
        {(uploadError || error) && (
          <div
            className="mx-4 mb-3 rounded-lg p-3 flex flex-col gap-2"
            style={{
              background: "rgba(248,113,113,0.06)",
              border: "1px solid rgba(248,113,113,0.2)",
            }}
          >
            <p className="text-[12px]" style={{ color: "var(--danger)" }}>
              {uploadError ?? error}
            </p>
            <button
              onClick={handleReset}
              className="self-start text-[11px] rounded px-2.5 py-1 transition-colors"
              style={{
                background: "rgba(248,113,113,0.12)",
                color: "var(--danger)",
                border: "1px solid rgba(248,113,113,0.2)",
              }}
            >
              Try Again
            </button>
          </div>
        )}

        {/* Data Quality section */}
        <div className="mx-4 mb-4 flex-1">
          <p
            className="text-[10px] font-semibold tracking-widest uppercase mb-2"
            style={{ color: "var(--text3)" }}
          >
            Data Quality
          </p>

          <div className="flex flex-col gap-2">
            {qualityRows.length > 0
              ? qualityRows.map(({ column, pct }) => (
                  <div key={column} className="flex items-center gap-2">
                    <span
                      className="text-[12px] w-24 truncate shrink-0"
                      style={{ color: "var(--text2)" }}
                    >
                      {column}
                    </span>
                    <div
                      className="flex-1 h-1 rounded-full overflow-hidden"
                      style={{ background: "var(--bg4)" }}
                    >
                      <div
                        className="h-full rounded-full"
                        style={{
                          width: `${Math.min(pct, 100)}%`,
                          background: "rgba(110,231,183,0.4)",
                        }}
                      />
                    </div>
                    <span
                      className="text-[10px] font-medium px-1.5 py-0.5 rounded shrink-0"
                      style={{
                        color: "var(--accent3)",
                        background: "rgba(251,191,36,0.12)",
                      }}
                    >
                      {pct.toFixed(1)}%
                    </span>
                  </div>
                ))
              : ["—", "—", "—"].map((_, i) => (
                  <div key={i} className="flex items-center gap-2">
                    <span
                      className="text-[12px] w-24"
                      style={{ color: "var(--text3)" }}
                    >
                      —
                    </span>
                    <div
                      className="flex-1 h-1 rounded-full"
                      style={{ background: "var(--bg4)" }}
                    />
                    <span
                      className="text-[10px] px-1.5 py-0.5 rounded"
                      style={{ color: "var(--text3)" }}
                    >
                      —
                    </span>
                  </div>
                ))}
          </div>
        </div>

        {/* Continue button */}
        <div className="p-4 mt-auto">
          <button
            disabled={!canContinue}
            onClick={() => canContinue && router.push("/context")}
            className="w-full rounded-lg py-2.5 text-[13px] font-medium transition-opacity"
            style={{
              background: "var(--accent)",
              color: "#000",
              opacity: canContinue ? 1 : 0.5,
              cursor: canContinue ? "pointer" : "not-allowed",
            }}
          >
            Continue to Context →
          </button>
        </div>
      </aside>

      {/* ── Right panel ── */}
      <main className="flex-1 flex flex-col overflow-hidden p-5">
        <Canvas result={result} status={status} progress={progress} />
      </main>
    </div>
  );
}
