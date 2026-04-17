# Group 1 — Upload + Auto EDA
**Date:** 2026-04-17  
**Approach:** Spec-faithful, must-have/nice-to-have split  
**Demo moment:** Drop a CSV → instant profiling, stat cards, and charts appear without any user input

---

## Scope

### Must-haves
- CSV upload via drag-and-drop and file picker (max 50MB)
- CSV → `raw_{upload_id}` SQLite table via pandas, with light type coercion pass
- `jobs` table + Fire & Poll backbone (reused by all async work in the app)
- AutoEDA LangGraph agent with 4 tools
- Agent always runs 7 fixed analyses
- Canvas renders: stat cards, up to 5 charts, quality warning badges
- "Go to Context →" button enabled only after EDA job completes
- NavBar showing step 1 of 3 active

### Nice-to-haves (only if time allows)
- Animated chart entrances (Recharts `isAnimationActive` prop)
- "Download raw profile JSON" button
- Column-level null heatmap chart

---

## Light Type Coercion (at upload time)

Applied to `raw_{upload_id}` immediately after CSV parse. Goal: make types query-safe without distorting data.

Rules (applied in order, per column):
1. Strip leading/trailing whitespace from all string values
2. Strip currency symbols and thousands separators from numeric-looking strings (`"$1,234.00"` → `1234.00`)
3. Parse mixed date format columns to ISO 8601 (`"15/01/2024"` and `"2024-01-15"` → `"2024-01-15"`)
4. Coerce columns where >80% of non-null values parse as numeric to REAL type
5. Never drop rows — if a value can't be coerced, leave it as TEXT

This step is a utility function (`csv_parser.py`), not an agent. No LLM involved.

---

## AutoEDA Agent

**Pattern:** LangGraph single-node agent with tool-calling loop.  
**Trigger:** Fires automatically in background after CSV is parsed.  
**Output:** `CanvasResponse` written to `jobs.result`.

### Role Persona
> "You are a senior data scientist doing a first-pass exploratory analysis of a new dataset. Your job is to quickly understand the shape, quality, and key distributions of the data before any cleaning or modeling. You produce a structured summary and a set of charts that give the analyst an immediate feel for what they're working with."

### Tools

```python
get_dataframe_profile(upload_id: str) -> dict
    # Returns: shape, dtypes, null counts, nunique per column,
    # basic describe() stats. Called once at agent start.
    # Reads from raw_{upload_id} SQLite table.

run_python_analysis(upload_id: str, code: str) -> str
    # Executes pandas/numpy code against raw_{upload_id}.
    # Returns stdout + any exception.
    # Restricted imports: pandas, numpy, scipy.stats only.
    # No file I/O. Timeout: 30s.

generate_chart_spec(
    chart_type: str,   # "bar" | "line" | "histogram" | "scatter" | "heatmap" | "boxplot"
    title: str,
    x_label: str,
    y_label: str,
    data: list[dict]   # [{"x": ..., "y": ...}]
) -> dict
    # Validates and returns a standardised ChartSpec JSON.
    # Does not render — frontend renders via Recharts.

write_autoeda_result(upload_id: str, canvas_response: dict) -> bool
    # Persists the final CanvasResponse to jobs.result.
    # Sets jobs.status = "done". Called once at end.
```

### 7 Fixed Analyses (agent always runs all)

1. Row count, column count, memory size
2. Null percentage per column — flag any column >5% nulls as `warning` insight
3. Duplicate row count — flag if >0
4. For each numeric column: skew, min, max, mean, median
5. For each categorical column with cardinality ≤20: value counts
6. Top 3 pairwise correlations (absolute value) among numeric columns
7. Datetime columns: min/max date range

### Chart Selection Logic (agent decides, not hardcoded)

| Data condition | Chart type |
|---|---|
| Numeric column, cardinality >20 | histogram |
| Categorical column, cardinality ≤10 | bar chart |
| Two numeric columns with \|correlation\| >0.5 | scatter |
| Datetime + numeric column | line chart |
| ≥4 numeric columns | correlation heatmap |

Maximum 5 charts rendered. Agent prioritises by informativeness.

### Output Contract

```json
{
  "insights": [
    { "type": "stat", "label": "Rows", "value": "12,450" },
    { "type": "stat", "label": "Columns", "value": "8" },
    { "type": "stat", "label": "Duplicates", "value": "200", "color": "amber" },
    { "type": "warning", "content": "revenue: 8.2% null values" },
    { "type": "warning", "content": "product_category: 3.1% null values" }
  ],
  "charts": [
    {
      "type": "histogram",
      "title": "Revenue Distribution",
      "x_label": "Revenue",
      "y_label": "Frequency",
      "data": [{ "x": 0, "y": 234 }, { "x": 100, "y": 891 }]
    }
  ],
  "table": null
}
```

---

## API Endpoints

```
POST /api/upload
  Body: multipart/form-data { file }
  Response: { upload_id: string, job_id: string, slug: string }
  Side effects:
    - Saves file to UPLOAD_DIR
    - Writes row to uploads table
    - Creates job row (status="pending")
    - Schedules background task: parse CSV → coerce types → run AutoEDA agent

GET /api/jobs/{job_id}
  Response: { job_id, status, result: CanvasResponse | null, error: string | null }
  Used by: Screen 1 polling, Screen 3 (Query Canvas loading check)
```

### FastAPI Implementation (simplified)

```python
@app.post("/api/upload")
async def upload_file(file: UploadFile, bg: BackgroundTasks):
    upload_id = str(uuid4())
    job_id = str(uuid4())
    slug = generate_slug(file.filename)        # "orders_2024.csv" → "orders_2024"
    # 1. Save file to UPLOAD_DIR
    # 2. Write uploads row
    # 3. Create job row (status="pending")
    bg.add_task(run_autoeda_pipeline, upload_id, job_id)
    return {"upload_id": upload_id, "job_id": job_id, "slug": slug}

async def run_autoeda_pipeline(upload_id: str, job_id: str):
    update_job(job_id, status="running")
    await parse_and_coerce_csv(upload_id)      # csv_parser.py
    result = await autoeda_agent.run(upload_id)
    update_job(job_id, status="done", result=result)
```

---

## Frontend — Screen 1

### Layout

```
┌─────────────────────┬──────────────────────────────────┐
│  LEFT (40%)         │  RIGHT (60%) — Canvas             │
│                     │                                    │
│  Drag-and-drop zone │  [Skeleton/spinner while running] │
│  File name + size   │                                    │
│  Row/col count      │  InsightCards (stat grid)          │
│  Upload status bar  │  Charts (up to 5)                  │
│                     │  Warning badges                    │
│  [→ Go to Context]  │                                    │
│  (disabled until    │                                    │
│   EDA complete)     │                                    │
└─────────────────────┴──────────────────────────────────┘
```

### Polling Hook

```typescript
// lib/hooks.ts
function usePolling(jobId: string, interval = 2000) {
  // polls GET /api/jobs/{jobId} until status="done" or "error"
  // returns { status, result: CanvasResponse | null, error }
}
```

### Component Tree

```
upload/page.tsx
├── NavBar (step 1 active)
├── UploadZone (drag-drop + file picker)
├── UploadStatus (filename, row/col count, progress)
├── Canvas (renders CanvasResponse from job result)
│   ├── InsightCards
│   └── ChartRenderer (Recharts)
└── Button "Go to Context →" (disabled until done)
```

### State Flow

1. User drops file → `POST /api/upload` → store `upload_id`, `job_id`, `slug` in `AppContext` + `localStorage`
2. Start polling `GET /api/jobs/{job_id}` every 2s
3. While `status = "running"`: show spinner on canvas, show file metadata on left
4. When `status = "done"`: stop polling, render `CanvasResponse` in Canvas
5. "Go to Context" button becomes active — navigates to `/context`

---

## Demo Dataset Notes

The demo CSV is a messy e-commerce orders file with intentional issues:
- `revenue`: 8% nulls, values stored with "$" prefix (coercion step handles this)
- `customer_id`: 200 duplicate rows
- `region`: mixed case ("north", "North", "NORTH")
- `order_date`: mixed date formats (coercion step normalises)
- `product_category`: 3% nulls
- `discount_pct`: 15 rows with values >100

The AutoEDA agent should surface: duplicate warning, null warnings for revenue and product_category, a revenue histogram, a region bar chart, and a discount_pct outlier note. All of these are produced by the 7 fixed analyses — no dataset-specific logic needed.
