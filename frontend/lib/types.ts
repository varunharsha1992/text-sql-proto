/** TypeScript interfaces mirroring backend/models.py exactly. */

export type InsightType = "stat" | "text" | "warning" | "badge";
export type InsightColor = "green" | "amber" | "red";

export interface InsightItem {
  type: InsightType;
  label?: string | null;
  value?: string | null;
  content?: string | null;
  color?: InsightColor | null;
}

export type ChartType =
  | "bar"
  | "line"
  | "histogram"
  | "scatter"
  | "heatmap"
  | "boxplot";

export interface ChartSpec {
  type: ChartType;
  title: string;
  x_label: string;
  y_label: string;
  data: Array<Record<string, string | number>>;
}

export interface TableData {
  columns: string[];
  rows: Array<Array<string | number | null>>;
}

export interface CanvasResponse {
  insights: InsightItem[];
  charts: ChartSpec[];
  table: TableData | null;
}

export interface UploadResponse {
  upload_id: string;
  job_id: string;
  slug: string;
}

export type JobStatus = "pending" | "running" | "done" | "error";

export interface JobResponse {
  job_id: string;
  status: JobStatus;
  result: CanvasResponse | null;
  error: string | null;
}
