"use client";

import { useUploadId } from "@/lib/hooks";
import { usePathname } from "next/navigation";

const STEPS = [
  { label: "Upload + EDA", path: "/upload" },
  { label: "Context", path: "/context" },
  { label: "Query Canvas", path: "/query" },
];

type StepState = "active" | "done" | "locked";

function getStepState(
  stepIndex: number,
  activeIndex: number,
  edaDone: boolean
): StepState {
  if (stepIndex === activeIndex) return "active";
  if (stepIndex < activeIndex) return "done";
  // Step 2 (context) unlocks only after EDA is done
  if (stepIndex === 1 && !edaDone) return "locked";
  // Step 3 (query) is always locked for now (requires context complete)
  if (stepIndex === 2) return "locked";
  return "locked";
}

export default function NavBar() {
  const pathname = usePathname();
  const { edaDone } = useUploadId();

  const activeIndex = STEPS.findIndex((s) => pathname?.startsWith(s.path));

  return (
    <nav
      className="h-11 flex items-center px-5 shrink-0 gap-0"
      style={{
        background: "var(--bg2)",
        borderBottom: "1px solid var(--border)",
      }}
    >
      {/* Brand */}
      <span
        className="text-[16px] font-semibold mr-8 tracking-tight"
        style={{
          fontFamily: "'Fraunces', serif",
          color: "var(--accent)",
        }}
      >
        DataLens
      </span>

      {/* Steps */}
      <div className="flex items-stretch gap-0">
        {STEPS.map((step, i) => {
          const state = getStepState(i, activeIndex, edaDone);
          const isLast = i === STEPS.length - 1;

          return (
            <div key={step.path} className="flex items-stretch">
              <div
                className="flex items-center gap-1.5 px-4 text-[12px] transition-colors whitespace-nowrap"
                style={{
                  color:
                    state === "active"
                      ? "var(--text)"
                      : state === "done"
                      ? "var(--text2)"
                      : "var(--text3)",
                  opacity: state === "locked" ? 0.35 : 1,
                  cursor: state === "locked" ? "not-allowed" : "default",
                  borderBottom:
                    state === "active"
                      ? "2px solid var(--accent)"
                      : "2px solid transparent",
                  paddingBottom: "2px",
                }}
              >
                {/* Step number / checkmark */}
                <span
                  className="w-[18px] h-[18px] rounded-full flex items-center justify-center text-[9px] shrink-0"
                  style={{
                    fontFamily: "'DM Mono', monospace",
                    border:
                      state === "active"
                        ? "1px solid var(--accent)"
                        : "1px solid var(--border2)",
                    background:
                      state === "active"
                        ? "var(--accent)"
                        : state === "done"
                        ? "rgba(110,231,183,0.15)"
                        : "transparent",
                    color:
                      state === "active"
                        ? "#000"
                        : state === "done"
                        ? "var(--accent)"
                        : "var(--text3)",
                  }}
                >
                  {state === "done" ? "✓" : i + 1}
                </span>
                {step.label}
              </div>
              {!isLast && (
                <span
                  className="text-[10px] px-0.5 flex items-center"
                  style={{ color: "var(--text3)" }}
                >
                  ›
                </span>
              )}
            </div>
          );
        })}
      </div>
    </nav>
  );
}
