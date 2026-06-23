"use client";

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { useRouter } from "next/navigation";
import { uploadFile } from "@/lib/api";
import { useUploadId, useUploads, usePolling } from "@/lib/hooks";
import Canvas from "@/components/Canvas";
import TableList from "@/components/TableList";

function formatBytes(bytes: number): string {
  if (bytes >= 1_048_576) return `${(bytes / 1_048_576).toFixed(1)} MB`;
  if (bytes >= 1_024) return `${(bytes / 1_024).toFixed(0)} KB`;
  return `${bytes} B`;
}

export default function UploadPage() {
  const fileInputRef = useRef<HTMLInputElement>(null);
  const [isDragging, setIsDragging] = useState(false);
  const [uploadError, setUploadError] = useState<string | null>(null);
  const [isUploading, setIsUploading] = useState(false);
  const [selectedId, setSelectedId] = useState<string | null>(null);

  const { uploads, loading, refetch } = useUploads();
  const { setEdaDone } = useUploadId();
  const router = useRouter();

  // Default the selected table to the first ready (or first) table.
  useEffect(() => {
    if (selectedId && uploads.some((u) => u.upload_id === selectedId)) return;
    const firstDone = uploads.find((u) => u.status === "done");
    const pick = firstDone ?? uploads[0];
    if (pick) setSelectedId(pick.upload_id);
  }, [uploads, selectedId]);

  const anyDone = uploads.some((u) => u.status === "done");
  useEffect(() => {
    if (anyDone) setEdaDone();
  }, [anyDone, setEdaDone]);

  const selected = useMemo(
    () => uploads.find((u) => u.upload_id === selectedId) ?? null,
    [uploads, selectedId]
  );
  const { status, result } = usePolling(selected?.job_id ?? null);

  const handleFiles = useCallback(
    async (files: FileList) => {
      setUploadError(null);
      setIsUploading(true);
      try {
        for (const f of Array.from(files)) {
          await uploadFile(f);
        }
        refetch();
      } catch (e) {
        setUploadError(e instanceof Error ? e.message : "Upload failed");
      } finally {
        setIsUploading(false);
      }
    },
    [refetch]
  );

  const onDrop = useCallback(
    (e: React.DragEvent) => {
      e.preventDefault();
      setIsDragging(false);
      if (e.dataTransfer.files?.length) handleFiles(e.dataTransfer.files);
    },
    [handleFiles]
  );

  const onFileInputChange = useCallback(
    (e: React.ChangeEvent<HTMLInputElement>) => {
      if (e.target.files?.length) handleFiles(e.target.files);
    },
    [handleFiles]
  );

  const canContinue = anyDone;

  return (
    <div className="flex h-screen overflow-hidden" style={{ background: "var(--bg)" }}>
      {/* Left panel */}
      <aside
        className="flex flex-col w-[360px] shrink-0 overflow-y-auto"
        style={{ background: "var(--bg2)", borderRight: "1px solid var(--border)" }}
      >
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
            onDragOver={(e) => {
              e.preventDefault();
              setIsDragging(true);
            }}
            onDragLeave={(e) => {
              e.preventDefault();
              setIsDragging(false);
            }}
            onDrop={onDrop}
          >
            <span className="text-3xl">📊</span>
            <p className="font-medium" style={{ color: "var(--text)" }}>
              Drop CSV files here
            </p>
            <p className="text-[12px]" style={{ color: "var(--text3)" }}>
              one or more · max 50MB each
            </p>
          </div>
          <input
            ref={fileInputRef}
            type="file"
            accept=".csv"
            multiple
            className="hidden"
            onChange={onFileInputChange}
          />
          {isUploading && (
            <p className="text-[12px] mt-2" style={{ color: "var(--text2)" }}>
              Uploading…
            </p>
          )}
          {uploadError && (
            <p className="text-[12px] mt-2" style={{ color: "var(--danger)" }}>
              {uploadError}
            </p>
          )}
        </div>

        <div className="mx-4 mb-4 flex-1">
          {loading && uploads.length === 0 ? (
            <p className="text-[12px]" style={{ color: "var(--text3)" }}>
              Loading tables…
            </p>
          ) : (
            <TableList
              uploads={uploads}
              selectedId={selectedId}
              onSelect={setSelectedId}
            />
          )}
        </div>

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

      {/* Right panel — selected table's canvas */}
      <main className="flex-1 flex flex-col overflow-hidden p-5">
        {selected ? (
          <Canvas result={result} status={status} />
        ) : (
          <div
            className="flex-1 flex items-center justify-center text-[12px]"
            style={{ color: "var(--text3)" }}
          >
            Upload a CSV to begin.
          </div>
        )}
      </main>
    </div>
  );
}
