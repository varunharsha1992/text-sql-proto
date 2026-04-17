# Data Model: CSV Upload and Auto EDA

**Branch**: `001-upload-auto-eda` | **Date**: 2026-04-17

---

## SQLite Tables Introduced by This Feature

### `uploads`

Stores metadata for each CSV file upload.

```sql
CREATE TABLE IF NOT EXISTS uploads (
    id                TEXT PRIMARY KEY,         -- UUID4, e.g. "a3f7c2d1-..."
    filename          TEXT NOT NULL,            -- original filename, e.g. "orders_2024.csv"
    slug              TEXT NOT NULL,            -- human-readable ID, e.g. "orders_2024"
    original_path     TEXT NOT NULL,            -- absolute path to saved file on disk
    row_count         INTEGER,                  -- set after CSV parse completes
    col_count         INTEGER,                  -- set after CSV parse completes
    uploaded_at       DATETIME DEFAULT CURRENT_TIMESTAMP,
    context_complete  BOOLEAN DEFAULT FALSE     -- set by Group 2 (Context Agent)
);
```

**Notes**:
- `id` is used in all downstream table references and API paths
- `slug` is returned in the upload response and stored in frontend `localStorage`
- `context_complete` is written by the Context Agent (Group 2) — not this feature
- No foreign key constraints (SQLite default; app logic enforces consistency)

---

### `jobs`

Tracks the lifecycle of all background agent tasks (Pattern A). Introduced here, reused by future features.

```sql
CREATE TABLE IF NOT EXISTS jobs (
    job_id      TEXT PRIMARY KEY,              -- UUID4
    job_type    TEXT NOT NULL,                 -- "autoeda" (this feature); "cleanup" in future
    upload_id   TEXT NOT NULL,                 -- references uploads.id
    status      TEXT NOT NULL DEFAULT "pending",  -- "pending" | "running" | "done" | "error"
    result      TEXT,                          -- JSON blob: CanvasResponse when done, NULL otherwise
    error       TEXT,                          -- error message string when status="error"
    created_at  DATETIME DEFAULT CURRENT_TIMESTAMP,
    updated_at  DATETIME DEFAULT CURRENT_TIMESTAMP
);
```

**Status transitions**:
```
pending → running  (when BackgroundTask picks up the job)
running → done     (when write_autoeda_result tool is called successfully)
running → error    (when any unhandled exception occurs in the pipeline)
```

**`result` shape when `status = "done"`** (JSON-serialised `CanvasResponse`):
```json
{
  "insights": [
    { "type": "stat", "label": "Rows", "value": "12,847" },
    { "type": "stat", "label": "Columns", "value": "11" },
    { "type": "stat", "label": "Duplicates", "value": "200", "color": "amber" },
    { "type": "warning", "content": "revenue: 12.4% null values" }
  ],
  "charts": [
    {
      "type": "histogram",
      "title": "Revenue Distribution",
      "x_label": "Revenue ($)",
      "y_label": "Frequency",
      "data": [{ "x": 0, "y": 234 }, { "x": 500, "y": 891 }]
    }
  ],
  "table": null
}
```

---

### `raw_{upload_id}` (dynamic table)

One table per upload, created from the CSV. Column names derived from CSV headers. Types inferred after coercion pass.

```sql
-- Example: raw_a3f7c2d1 (for upload_id = "a3f7c2d1-...")
-- Schema is dynamic — columns match CSV headers after coercion
-- Example for demo dataset:
CREATE TABLE IF NOT EXISTS raw_a3f7c2d1 (
    order_id          TEXT,
    customer_id       TEXT,
    order_date        TEXT,    -- ISO 8601 after coercion
    region            TEXT,
    product_category  TEXT,
    revenue           REAL,    -- numeric after "$" strip + coercion
    discount_pct      REAL,
    quantity          INTEGER,
    ...
);
```

**Coercion rules applied before write**:
1. Whitespace stripped from all string values
2. Currency prefix/thousands separator removed from numeric-looking strings
3. Mixed date formats normalised to ISO 8601
4. Columns >80% numeric coerced to `REAL`
5. Unconvertible values stored as `TEXT` — no rows dropped

**Who reads this table**: AutoEDA agent tools (`get_dataframe_profile`, `run_python_analysis`). Query Canvas agent (`execute_sql`) in Group 3.  
**Who writes this table**: `csv_parser.py` utility — called once per upload.

---

## Database Helper Functions (`database.py`)

These functions are the only permitted way to interact with the above tables from application code.

```python
async def create_tables(db: aiosqlite.Connection) -> None:
    """Create uploads and jobs tables if they don't exist."""

async def create_upload(upload_id: str, filename: str, slug: str, path: str) -> None:
    """Insert a new row into uploads table."""

async def update_upload_counts(upload_id: str, row_count: int, col_count: int) -> None:
    """Set row_count and col_count after CSV parse completes."""

async def create_job(job_id: str, job_type: str, upload_id: str) -> None:
    """Insert a new pending job row."""

async def update_job(job_id: str, status: str, result: str = None, error: str = None) -> None:
    """Update job status, and optionally set result or error."""

async def get_job(job_id: str) -> dict:
    """Fetch a single job row as a dict. Returns None if not found."""
```

---

## Entity Definitions

### Upload

| Attribute | Type | Description |
|-----------|------|-------------|
| `id` | `str` (UUID4) | Primary key. Used in all API paths and table names. |
| `filename` | `str` | Original uploaded filename including extension. |
| `slug` | `str` | Human-readable identifier derived from filename. Displayed in NavBar. |
| `original_path` | `str` | Absolute path to the saved CSV file on disk. |
| `row_count` | `int \| None` | Set after parse. `None` until CSV parsing completes. |
| `col_count` | `int \| None` | Set after parse. `None` until CSV parsing completes. |
| `uploaded_at` | `datetime` | Timestamp of the upload request. |
| `context_complete` | `bool` | Set to `True` by Context Agent (Group 2). |

### Analysis Job

| Attribute | Type | Description |
|-----------|------|-------------|
| `job_id` | `str` (UUID4) | Primary key. Returned to frontend for polling. |
| `job_type` | `str` | `"autoeda"` for this feature. |
| `upload_id` | `str` | References the Upload this job belongs to. |
| `status` | `str` | One of: `pending`, `running`, `done`, `error`. |
| `result` | `str \| None` | JSON-serialised `CanvasResponse`. Present only when `status = "done"`. |
| `error` | `str \| None` | Error message. Present only when `status = "error"`. |
| `created_at` | `datetime` | Job creation timestamp. |
| `updated_at` | `datetime` | Last status change timestamp. |

### CanvasResponse (output contract)

Defined in `frontend/lib/types.ts` and mirrored as Pydantic models in `backend/models.py`.

| Field | Type | Description |
|-------|------|-------------|
| `insights` | `InsightItem[]` | Ordered list of stat cards and warning banners. |
| `charts` | `ChartSpec[]` | List of chart specs (max 5 for AutoEDA). |
| `table` | `TableData \| null` | Always `null` for AutoEDA (no tabular query results). |

**InsightItem variants**:

| `type` | Required fields | Optional fields | Usage |
|--------|----------------|-----------------|-------|
| `stat` | `label`, `value` | `color` | Key numbers: row count, null count, duplicate count |
| `warning` | `content` | `color` | Column-level quality alerts |
| `text` | `content` | — | Narrative observations |
| `badge` | `content` | `color` | Short status labels |

**Colors**: `green` (healthy), `amber` (attention needed), `red` (critical issue)

### ChartSpec

| Field | Type | Description |
|-------|------|-------------|
| `type` | `str` | One of: `bar`, `line`, `histogram`, `scatter`, `heatmap`, `boxplot` |
| `title` | `str` | Human-readable chart title |
| `x_label` | `str` | X-axis label |
| `y_label` | `str` | Y-axis label |
| `data` | `{ x: str \| number, y: number }[]` | Normalised data points |
