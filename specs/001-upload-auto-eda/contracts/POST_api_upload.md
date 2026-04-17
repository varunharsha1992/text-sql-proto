# Contract: POST /api/upload

**Feature**: 001-upload-auto-eda  
**Pattern**: A (Fire & Poll) — returns immediately, agent runs in background

---

## Request

```
POST /api/upload
Content-Type: multipart/form-data
```

| Field | Type | Required | Constraints |
|-------|------|----------|-------------|
| `file` | File (multipart) | Yes | CSV only. Max 50MB. |

**Validation**:
- Content-type must be `text/csv` or filename must end in `.csv`
- File size must be ≤ `MAX_FILE_SIZE_MB` (env var, default 50)
- Reject immediately with `400` if either constraint fails

---

## Response — Success

```
HTTP 200 OK
Content-Type: application/json
```

```json
{
  "upload_id": "a3f7c2d1-4e5f-6a7b-8c9d-0e1f2a3b4c5d",
  "job_id":    "b4e8d3c2-5f6a-7b8c-9d0e-1f2a3b4c5d6e",
  "slug":      "orders_2024"
}
```

| Field | Type | Description |
|-------|------|-------------|
| `upload_id` | `string` (UUID4) | Stable identifier for this dataset. Used in all subsequent API calls. |
| `job_id` | `string` (UUID4) | Identifier to poll for EDA completion. |
| `slug` | `string` | Human-readable label derived from filename. Displayed in NavBar. |

**Side effects on success**:
1. File saved to `UPLOAD_DIR/{upload_id}.csv`
2. Row inserted into `uploads` table (`status = pending`)
3. Row inserted into `jobs` table (`job_type = "autoeda"`, `status = "pending"`)
4. Background pipeline scheduled: `parse_csv → coerce_types → run_autoeda_agent`

---

## Response — Errors

| Scenario | HTTP Status | `detail` value |
|----------|-------------|----------------|
| Not a CSV file | `400 Bad Request` | `"Only CSV files are accepted."` |
| File exceeds 50MB | `400 Bad Request` | `"File size exceeds 50MB limit."` |
| Server error during save | `500 Internal Server Error` | `"Upload failed: {error message}"` |

```json
{ "detail": "Only CSV files are accepted." }
```

---

## Frontend Usage

```typescript
// lib/api.ts
async function uploadFile(file: File): Promise<{ upload_id: string; job_id: string; slug: string }>

// lib/hooks.ts — called once on file drop/select
const { upload_id, job_id, slug } = await uploadFile(file)
setUploadId(upload_id)     // stored in context + localStorage
setSlug(slug)
startPolling(job_id)       // begins usePolling(job_id)
```

---

## Notes

- Response is returned **before** the background pipeline starts. The frontend must not assume the EDA is complete when this response arrives.
- `upload_id` and `job_id` must both be stored in `localStorage` — they are needed if the user refreshes the page.
- The `slug` is display-only; it is not used as a database key.
