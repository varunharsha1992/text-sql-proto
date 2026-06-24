# DataLens

Local analytics app: upload CSVs → AutoEDA profiles them → optional context interview → ask natural-language questions over a **connected multi-table schema**.

**Stack:** Next.js 14 · FastAPI · LangGraph / DeepAgents · OpenRouter · SQLite · FastMCP (Cowork)

Full architecture, MCP tool reference, and API docs: [`docs/datalens.md`](docs/datalens.md)

---

## Prerequisites

- **Python 3.11+**
- **Node.js 18+** (for the web UI)
- **OpenRouter API key** ([openrouter.ai](https://openrouter.ai)) — agents use DeepSeek V4 Flash

---

## Quick start (web UI)

### 1. Clone and configure environment

From the repo root:

```bash
cp .env.example .env   # if you have an example; otherwise create .env manually
```

Create **`.env`** at the repo root (gitignored):

```env
OPENROUTER_API_KEY=sk-or-your-key-here
OPENROUTER_MODEL=deepseek/deepseek-v4-flash
DATABASE_URL=sqlite+aiosqlite:///./data/app.db
UPLOAD_DIR=./data/uploads
MAX_FILE_SIZE_MB=50
AGENT_TIMEOUT_SEC=240
```

### 2. Backend (API — port **8000**)

```bash
pip install -r backend/requirements.txt
# Windows PowerShell:
$env:PYTHONPATH="."
python -m uvicorn backend.main:app --host 127.0.0.1 --port 8000

# macOS / Linux:
PYTHONPATH=. python -m uvicorn backend.main:app --host 127.0.0.1 --port 8000
```

API docs: http://127.0.0.1:8000/docs

Use **one** uvicorn process on `:8000`. Avoid `--reload` while debugging route issues — stale listeners can cause 404s.

### 3. Frontend (web UI — port **3000**)

```bash
cd frontend
npm install
```

Create **`frontend/.env.local`** (gitignored):

```env
NEXT_PUBLIC_API_URL=http://127.0.0.1:8000
```

Then:

```bash
npm run dev
```

Open **http://localhost:3000**

| Port | Service |
|------|---------|
| **3000** | Next.js UI (what you open in the browser) |
| **8000** | FastAPI backend (API + agents) |

`NEXT_PUBLIC_API_URL` tells the browser to call the **backend on 8000 directly**. Without it, requests go through Next’s dev proxy (`/api` → `:8000`), which can **timeout (~60s)** on long agent turns (Context / Query). The UI stays on 3000 either way.

### 4. Walk through the app

1. **Upload** — `/upload` — upload CSV(s), wait for AutoEDA
2. **Context** — `/context` — optional schema interview
3. **Query** — `/query` — ask questions spanning all uploaded tables

Smoke CSVs: `test-data/smoke/smoke_customers.csv`, `test-data/smoke/smoke_orders.csv`

---

## Quick start (Claude Cowork / MCP)

Requires the **backend on :8000** plus the **MCP server on :8010**.

```bash
# Terminal 1 — backend (same as above)
$env:PYTHONPATH="."   # PowerShell
python -m uvicorn backend.main:app --host 127.0.0.1 --port 8000

# Terminal 2 — MCP
pip install -r datalens_mcp/requirements.txt
$env:PYTHONPATH="."
python -m datalens_mcp
# → http://127.0.0.1:8010/mcp
```

**Cowork connector:**

```json
{
  "datalens": {
    "type": "streamable-http",
    "url": "http://127.0.0.1:8010/mcp"
  }
}
```

**Tools:** `analyze_csv` · `context_chat` · `query_chat` — see [`docs/datalens.md`](docs/datalens.md#mcp-server-for-claude-cowork)

---

## Verify setup (optional)

With backend running on `:8000`:

```bash
# Full pipeline (~8 min, needs OPENROUTER_API_KEY)
$env:PYTHONPATH="."
python scripts/smoke_mcp_full.py

# Context + query only (~3 min)
python scripts/smoke_mcp_context_query.py
```

---

## Project layout

```text
backend/           FastAPI, agents, SQLite
frontend/          Next.js 14 App Router
datalens_mcp/      FastMCP server (Cowork)
test-data/smoke/   Sample CSVs
docs/datalens.md   Full product + MCP reference
docs/superpowers/  Feature specs and implementation plans
```

---

## Troubleshooting

| Issue | Fix |
|-------|-----|
| 404 on new API routes | Kill all processes on port 8000; start a single uvicorn |
| Context/Query times out in UI | Set `NEXT_PUBLIC_API_URL=http://127.0.0.1:8000` in `frontend/.env.local` |
| MCP tool errors “API unreachable” | Start FastAPI on `:8000` before MCP |
| Agent errors | Check `OPENROUTER_API_KEY` in repo-root `.env` |

---

## Development

```bash
# Backend lint/tests (from repo root)
cd backend && pytest && ruff check .
```

Feature design docs live under `docs/superpowers/specs/`.
