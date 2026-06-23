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

export type SemanticType =
  | "identifier"
  | "categorical"
  | "numeric"
  | "temporal"
  | "currency"
  | "boolean"
  | "text";

export interface DataDictionaryEntry {
  column: string;
  dtype: string;
  semantic_type: SemanticType;
  description: string;
  sample_values: string[];
  null_pct: number;
  unit?: string | null;
  is_pii: boolean;
}

export type Aggregation =
  | "sum"
  | "avg"
  | "count"
  | "count_distinct"
  | "min"
  | "max"
  | "median";

export interface Measure {
  name: string;
  column: string;
  aggregation: Aggregation;
  description: string;
}

export interface Dimension {
  name: string;
  column: string;
  description: string;
}

export interface Entity {
  name: string;
  description: string;
  key_columns: string[];
}

export interface SemanticLayer {
  grain: string;
  entities: Entity[];
  measures: Measure[];
  dimensions: Dimension[];
  time_dimension?: string | null;
  suggested_questions: string[];
}

export type ProgressStatus = "pending" | "in_progress" | "completed";

export interface ProgressItem {
  text: string;
  status: ProgressStatus;
}

export interface CanvasResponse {
  insights: InsightItem[];
  charts: ChartSpec[];
  table: TableData | null;
  data_dictionary?: DataDictionaryEntry[] | null;
  semantic_layer?: SemanticLayer | null;
}

export interface UploadResponse {
  upload_id: string;
  job_id: string;
  slug: string;
}

export interface UploadSummary {
  upload_id: string;
  slug: string;
  filename: string;
  row_count?: number | null;
  col_count?: number | null;
  job_id?: string | null;
  status?: JobStatus | null;
}

export interface UploadsListResponse {
  uploads: UploadSummary[];
}

export type JobStatus = "pending" | "running" | "done" | "error";

export interface JobResponse {
  job_id: string;
  status: JobStatus;
  result: CanvasResponse | null;
  error: string | null;
  progress?: ProgressItem[] | null;
}
