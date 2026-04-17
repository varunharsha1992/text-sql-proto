# Quickstart: CSV Upload and Auto EDA

**Branch**: `001-upload-auto-eda` | **Date**: 2026-04-17  
Local development setup for running this feature end-to-end.

---

## Prerequisites

- Python 3.11+
- Node.js 18+
- An OpenAI API key with GPT-4o access

---

## 1. Clone and checkout branch

```bash
git checkout 001-upload-auto-eda
```

---

## 2. Backend setup

```powershell
# From repo root
cd backend
pip install -r requirements.txt --break-system-packages
```

**`requirements.txt`** (minimum for this feature):
```
fastapi
uvicorn[standard]
python-multipart
aiosqlite
pandas
numpy
scipy
langchain
langchain-openai
langgraph
python-dotenv
```

---

## 3. Environment variables

Create `.env` in the repo root:

```env
OPENAI_API_KEY=sk-...
DATABASE_URL=sqlite+aiosqlite:///./data/app.db
UPLOAD_DIR=./data/uploads
MAX_FILE_SIZE_MB=50
PYTHON_REPL_TIMEOUT_SEC=30
```

---

## 4. Create data directories

```powershell
mkdir data
mkdir data\uploads
```

---

## 5. Start the backend

```powershell
# From repo root
uvicorn backend.main:app --reload --port 8000
```

The server will create `data/app.db` and all tables on first startup.

Verify it's running:
```
GET http://localhost:8000/docs
```
The FastAPI auto-docs should show `POST /api/upload` and `GET /api/jobs/{job_id}`.

---

## 6. Frontend setup

```powershell
# From repo root
cd frontend
npm install
npm run dev
```

Frontend runs at `http://localhost:3000`.

---

## 7. Smoke test with demo dataset

The demo CSV is a messy e-commerce orders file. If not yet present, create it at `data/demo/ecommerce_orders_2024.csv` — see the demo dataset notes in `docs/superpowers/specs/2026-04-17-group1-upload-autoeda.md` for the required structure.

1. Open `http://localhost:3000/upload`
2. Drag and drop `ecommerce_orders_2024.csv` onto the upload zone
3. Observe left panel: filename, row count, column count appear
4. Observe right canvas: loading spinner while EDA runs (10–30s)
5. Canvas populates with:
   - 4 stat cards (rows, nulls, duplicates, date range)
   - At least 2 warning badges (revenue nulls, discount_pct outliers)
   - At least 2 charts (revenue histogram, region bar chart)
6. "Continue to Context →" button becomes active
7. NavBar shows step 1 complete

---

## 8. Verify SQLite state

After a successful upload + EDA:

```powershell
# From repo root — inspect the database
python -c "
import sqlite3, json
db = sqlite3.connect('data/app.db')
uploads = db.execute('SELECT id, slug, row_count, col_count FROM uploads').fetchall()
print('Uploads:', uploads)
jobs = db.execute('SELECT job_id, status, job_type FROM jobs').fetchall()
print('Jobs:', jobs)
tables = db.execute(\"SELECT name FROM sqlite_master WHERE type='table'\").fetchall()
print('Tables:', tables)
"
```

Expected output:
```
Uploads: [('a3f7c2d1-...', 'ecommerce_orders_2024', 12847, 11)]
Jobs: [('b4e8d3c2-...', 'done', 'autoeda')]
Tables: [('uploads',), ('jobs',), ('raw_a3f7c2d1...',)]
```

---

## Troubleshooting

| Symptom | Likely cause | Fix |
|---------|-------------|-----|
| Canvas never leaves loading state | EDA agent failed | Check backend logs; inspect `jobs` table `status` and `error` columns |
| `400 Bad Request` on upload | File too large or wrong type | Ensure file is `.csv` under 50MB |
| `OpenAI API error` in backend logs | Invalid or missing API key | Check `.env` OPENAI_API_KEY value |
| `ModuleNotFoundError` on startup | Missing dependency | Re-run `pip install -r requirements.txt --break-system-packages` |
| Charts missing but stats present | Agent chart selection returned 0 charts | Check backend logs for `generate_chart_spec` errors |
