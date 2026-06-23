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

export interface SchemaTable {
  name: string;
  grain: string;
  description: string;
}

export type RelationshipKind =
  | "one_to_many"
  | "many_to_one"
  | "one_to_one"
  | "many_to_many";

export interface Relationship {
  from_table: string;
  from_column: string;
  to_table: string;
  to_column: string;
  kind?: RelationshipKind | null;
  confidence?: number | null;
}

export interface SchemaMeasure {
  name: string;
  table: string;
  column: string;
  aggregation: Aggregation;
  description: string;
}

export interface SchemaDimension {
  name: string;
  table: string;
  column: string;
  description: string;
}

export interface SchemaSemanticLayer {
  tables: SchemaTable[];
  relationships: Relationship[];
  measures: SchemaMeasure[];
  dimensions: SchemaDimension[];
  suggested_questions: string[];
}

export type CatalogRole = "identifier" | "datetime" | "measure" | "dimension";

export interface CatalogRow {
  upload_id: string;
  slug: string;
  column_name: string;
  data_type?: string | null;
  semantic_role?: CatalogRole | null;
  business_context?: string | null;
  description?: string | null;
  is_primary_key: boolean;
  is_foreign_key: boolean;
  foreign_key_ref?: string | null;
  is_pii: boolean;
  unit?: string | null;
  sample_values: string[];
  null_pct?: number | null;
}

export interface ContextChatRequest {
  message: string;
}

export interface ContextChatResponse {
  chat: string;
  canvas: CanvasResponse;
  catalog: CatalogRow[];
  semantic_layer?: SchemaSemanticLayer | null;
  complete: boolean;
}

export interface SchemaResponse {
  catalog: CatalogRow[];
  semantic_layer?: SchemaSemanticLayer | null;
}
