# Contract: GET /api/jobs/{job_id}

**Feature**: 001-upload-auto-eda (introduced here, reused by all future async features)  
**Pattern**: A (Fire & Poll) — polled by frontend every 2s until `status = "done"` or `"error"`

---

## Request

```
GET /api/jobs/{job_id}
```

| Parameter | Location | Type | Description |
|-----------|----------|------|-------------|
| `job_id` | Path | `string` (UUID4) | Job identifier returned by `POST /api/upload` |

---

## Response — Job in progress

```
HTTP 200 OK
Content-Type: application/json
```

```json
{
  "job_id":    "b4e8d3c2-5f6a-7b8c-9d0e-1f2a3b4c5d6e",
  "status":    "running",
  "result":    null,
  "error":     null
}
```

---

## Response — Job complete

```json
{
  "job_id": "b4e8d3c2-5f6a-7b8c-9d0e-1f2a3b4c5d6e",
  "status": "done",
  "result": {
    "insights": [
      { "type": "stat",    "label": "Rows",       "value": "12,847" },
      { "type": "stat",    "label": "Columns",    "value": "11" },
      { "type": "stat",    "label": "Duplicates", "value": "200", "color": "amber" },
      { "type": "stat",    "label": "Date Range", "value": "Jan–Dec 2024" },
      { "type": "warning", "content": "revenue: 12.4% null values" },
      { "type": "warning", "content": "discount_pct: 15 values exceed 100 (outliers)" }
    ],
    "charts": [
      {
        "type":    "histogram",
        "title":   "Revenue Distribution",
        "x_label": "Revenue ($)",
        "y_label": "Frequency",
        "data":    [{ "x": 0, "y": 234 }, { "x": 500, "y": 891 }]
      },
      {
        "type":    "bar",
        "title":   "Orders by Region",
        "x_label": "Region",
        "y_label": "Order Count",
        "data":    [{ "x": "North", "y": 3200 }, { "x": "East", "y": 4100 }]
      }
    ],
    "table": null
  },
  "error": null
}
```

---

## Response — Job failed

```json
{
  "job_id": "b4e8d3c2-5f6a-7b8c-9d0e-1f2a3b4c5d6e",
  "status": "error",
  "result": null,
  "error":  "AutoEDA agent failed: OpenAI API timeout"
}
```

---

## Response — Job not found

```
HTTP 404 Not Found
Content-Type: application/json
```

```json
{ "detail": "Job not found." }
```

---

## Response Field Reference

| Field | Type | Description |
|-------|------|-------------|
| `job_id` | `string` | Echo of the requested job ID |
| `status` | `"pending" \| "running" \| "done" \| "error"` | Current lifecycle state |
| `result` | `CanvasResponse \| null` | Populated only when `status = "done"` |
| `error` | `string \| null` | Populated only when `status = "error"` |

---

## Frontend Usage

```typescript
// lib/hooks.ts
function usePolling(jobId: string, interval = 2000) {
  // Calls GET /api/jobs/{jobId} every `interval` ms
  // Stops polling when status is "done" or "error"
  // Returns: { status, result: CanvasResponse | null, error: string | null }
}

// In upload/page.tsx:
const { status, result, error } = usePolling(jobId)

if (status === "done" && result) {
  // render Canvas with result
}
if (status === "error") {
  // show error message + retry button
}
```

---

## Polling Behaviour

| State | Frontend action |
|-------|----------------|
| `pending` | Show spinner. Continue polling. |
| `running` | Show progress indicator. Continue polling. |
| `done` | Stop polling. Render `result` in Canvas. Enable "Continue →" button. |
| `error` | Stop polling. Show error message. Show retry button (re-calls `POST /api/upload`). |

**Interval**: 2000ms (2 seconds) — configurable via hook parameter.  
**Timeout**: No hard client-side timeout. User can refresh if something hangs.

---

## Notes

- This endpoint is stateless — no session or auth required.
- It is shared infrastructure: future features (Group 2 cleanup trigger) will create their own jobs using the same table and poll this same endpoint.
- The `result` field is always the full `CanvasResponse` — not paginated, not streamed.
