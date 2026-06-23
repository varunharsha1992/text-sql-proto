"use client";

import {
  BarChart,
  Bar,
  LineChart,
  Line,
  ScatterChart,
  Scatter,
  ComposedChart,
  XAxis,
  YAxis,
  Tooltip,
  ResponsiveContainer,
} from "recharts";
import type { ChartSpec } from "@/lib/types";

interface ChartRendererProps {
  spec: ChartSpec;
}

/** Map label/value (and similar LLM aliases) to x/y for Recharts. */
function normalizeChartData(
  data: Array<Record<string, string | number>>
): Array<Record<string, string | number>> {
  return data.map((item) => {
    if ("x" in item && "y" in item) return item;
    const x = item.label ?? item.name ?? item.category;
    const y = item.value;
    if (x !== undefined && y !== undefined) return { x, y };
    return item;
  });
}

function chartSpecForRender(spec: ChartSpec): ChartSpec {
  return { ...spec, data: normalizeChartData(spec.data) };
}

const tooltipStyle = {
  background: "var(--bg4)",
  border: "1px solid var(--border)",
  color: "var(--text)",
};

const tickStyle = { fill: "var(--text3)", fontSize: 10 };

function HeatmapChart({ spec }: { spec: ChartSpec }) {
  type HeatCell = { x: string; y: string; value: number };
  const cells = spec.data as unknown as HeatCell[];

  const xLabels = Array.from(new Set(cells.map((d) => d.x)));
  const yLabels = Array.from(new Set(cells.map((d) => d.y)));

  const lookup = new Map(cells.map((d) => [`${d.x}::${d.y}`, d.value]));

  return (
    <div
      className="overflow-auto"
      style={{ maxHeight: 200, fontSize: 9, color: "var(--text3)" }}
    >
      <table style={{ borderCollapse: "collapse", width: "100%" }}>
        <thead>
          <tr>
            <th style={{ padding: "2px 4px" }} />
            {xLabels.map((col) => (
              <th
                key={col}
                style={{
                  padding: "2px 4px",
                  fontWeight: 500,
                  maxWidth: 60,
                  overflow: "hidden",
                  textOverflow: "ellipsis",
                  whiteSpace: "nowrap",
                }}
                title={col}
              >
                {col}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {yLabels.map((row) => (
            <tr key={row}>
              <td
                style={{
                  padding: "2px 4px",
                  fontWeight: 500,
                  whiteSpace: "nowrap",
                }}
              >
                {row}
              </td>
              {xLabels.map((col) => {
                const val = lookup.get(`${col}::${row}`) ?? 0;
                const abs = Math.abs(val);
                const bg =
                  val >= 0
                    ? `rgba(var(--accent-rgb, 34 197 94) / ${abs})`
                    : `rgba(var(--danger-rgb, 239 68 68) / ${abs})`;
                return (
                  <td
                    key={col}
                    title={`${col} × ${row}: ${val.toFixed(2)}`}
                    style={{
                      padding: 2,
                      background: bg,
                      textAlign: "center",
                      minWidth: 28,
                      height: 24,
                      cursor: "default",
                    }}
                  >
                    {val.toFixed(2)}
                  </td>
                );
              })}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

function renderChart(spec: ChartSpec) {
  switch (spec.type) {
    case "bar":
      return (
        <ResponsiveContainer width="100%" height={200}>
          <BarChart data={spec.data}>
            <XAxis dataKey="x" tick={tickStyle} />
            <YAxis tick={tickStyle} />
            <Tooltip contentStyle={tooltipStyle} />
            <Bar dataKey="y" fill="var(--accent)" radius={[3, 3, 0, 0]} />
          </BarChart>
        </ResponsiveContainer>
      );

    case "histogram":
      return (
        <ResponsiveContainer width="100%" height={200}>
          <BarChart data={spec.data} barCategoryGap={1}>
            <XAxis dataKey="x" tick={tickStyle} />
            <YAxis tick={tickStyle} />
            <Tooltip contentStyle={tooltipStyle} />
            <Bar dataKey="y" fill="var(--accent2)" radius={[2, 2, 0, 0]} />
          </BarChart>
        </ResponsiveContainer>
      );

    case "line":
      return (
        <ResponsiveContainer width="100%" height={200}>
          <LineChart data={spec.data}>
            <XAxis dataKey="x" tick={tickStyle} />
            <YAxis tick={tickStyle} />
            <Tooltip contentStyle={tooltipStyle} />
            <Line
              type="monotone"
              dataKey="y"
              stroke="var(--accent)"
              strokeWidth={1.5}
              dot={false}
            />
          </LineChart>
        </ResponsiveContainer>
      );

    case "scatter":
      return (
        <ResponsiveContainer width="100%" height={200}>
          <ScatterChart>
            <XAxis
              type="number"
              dataKey="x"
              name={spec.x_label}
              tick={tickStyle}
            />
            <YAxis
              type="number"
              dataKey="y"
              name={spec.y_label}
              tick={tickStyle}
            />
            <Tooltip
              cursor={{ strokeDasharray: "3 3" }}
              contentStyle={tooltipStyle}
            />
            <Scatter data={spec.data} fill="var(--accent2)" />
          </ScatterChart>
        </ResponsiveContainer>
      );

    case "heatmap":
      return <HeatmapChart spec={spec} />;

    case "boxplot":
      return (
        <ResponsiveContainer width="100%" height={200}>
          <ComposedChart data={spec.data}>
            <XAxis dataKey="x" tick={tickStyle} />
            <YAxis tick={tickStyle} />
            <Tooltip contentStyle={tooltipStyle} />
            <Bar dataKey="y" fill="var(--blue)" radius={[3, 3, 0, 0]} />
          </ComposedChart>
        </ResponsiveContainer>
      );

    default: {
      const exhaustive: never = spec.type;
      return (
        <div
          className="h-[200px] flex items-center justify-center text-xs"
          style={{ color: "var(--text3)" }}
        >
          Chart type &ldquo;{exhaustive}&rdquo; not supported
        </div>
      );
    }
  }
}

export default function ChartRenderer({ spec }: ChartRendererProps) {
  const normalized = chartSpecForRender(spec);
  return (
    <div
      className="bg-[var(--bg3)] border border-[var(--border)] rounded-lg p-4 flex flex-col gap-3"
    >
      {normalized.title && (
        <p
          className="font-medium truncate"
          style={{ fontSize: 11, color: "var(--text2)" }}
        >
          {normalized.title}
        </p>
      )}
      {renderChart(normalized)}
    </div>
  );
}
