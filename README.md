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

API docs: [http://127.0.0.1:8000/docs](http://127.0.0.1:8000/docs)

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

Open **[http://localhost:3000](http://localhost:3000)**


| Port     | Service                                   |
| -------- | ----------------------------------------- |
| **3000** | Next.js UI (what you open in the browser) |
| **8000** | FastAPI backend (API + agents)            |


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

> **Cowork note:** Connectors need a **public HTTPS** MCP URL. `http://127.0.0.1:8010` usually will not work. Use [Horizon deploy](#horizon-deploy-cowork--public-mcp) below, or tunnel local MCP with ngrok.

---

## Horizon deploy (Cowork + public MCP)

Use the **same repo** on [Prefect Horizon](https://horizon.prefect.io). Horizon runs only `datalens_mcp/` — not `backend/` or `frontend/`. Your FastAPI backend stays local (or deploy it separately later).

### Architecture

```text
Cowork  →  https://your-server.fastmcp.app/mcp   (Horizon MCP)
                ↓  DATALENS_API_URL
           https://xxxx.ngrok-free.app             (tunnel to your laptop)
                ↓
           localhost:8000 + repo-root .env       (OPENROUTER_API_KEY, SQLite)
```

No database or storage migration required for this pattern — SQLite and `./data/uploads` stay on your machine.

### 1. Horizon settings

| Setting | Value |
|---------|-------|
| **Repo** | `varunharsha1992/text-sql-proto` |
| **Branch** | `002-connected-schema-context` (or `main` after merge) |
| **Entrypoint** | `datalens_mcp/server.py:mcp` |
| **Requirements** | Root [`requirements.txt`](requirements.txt) (auto-detected) |
| **Authentication** | On (recommended — OAuth for Cowork) |

### 2. Environment variables (Horizon UI)

**Required:**

| Variable | Example |
|----------|---------|
| `DATALENS_API_URL` | `https://abc123.ngrok-free.app` |

**Optional** (defaults in `datalens_mcp/config.py`):

| Variable | Default | When to bump |
|----------|---------|--------------|
| `DATALENS_JOB_TIMEOUT_SEC` | `300` | Long AutoEDA → `600` |
| `DATALENS_QUERY_TIMEOUT_SEC` | `300` | Long query turns → `600` |

**Not on Horizon** (backend only, in repo-root `.env`): `OPENROUTER_API_KEY`, `DATABASE_URL`, `UPLOAD_DIR`.

### 3. Expose local backend with ngrok

```powershell
# Terminal 1 — backend
$env:PYTHONPATH="."
python -m uvicorn backend.main:app --host 127.0.0.1 --port 8000

# Terminal 2 — tunnel (install ngrok, add authtoken first)
ngrok http 8000
```

Copy the **https** forwarding URL into Horizon as `DATALENS_API_URL` (no trailing slash). Update it whenever ngrok restarts on the free tier.

### 4. Cowork connector

Use the Horizon URL (not ngrok for MCP):

```text
https://your-server-name.fastmcp.app/mcp
```

Complete OAuth when prompted. Test tools in Horizon **Inspector** before Cowork.

Docs: [FastMCP Horizon guide](https://gofastmcp.com/deployment/prefect-horizon)

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


| Issue                             | Fix                                                                      |
| --------------------------------- | ------------------------------------------------------------------------ |
| 404 on new API routes             | Kill all processes on port 8000; start a single uvicorn                  |
| Context/Query times out in UI     | Set `NEXT_PUBLIC_API_URL=http://127.0.0.1:8000` in `frontend/.env.local` |
| MCP tool errors “API unreachable” | Start FastAPI on `:8000`; set Horizon `DATALENS_API_URL` to ngrok HTTPS URL |
| Cowork rejects localhost MCP      | Deploy MCP on Horizon; tunnel backend with ngrok                           |
| Agent errors                      | Check `OPENROUTER_API_KEY` in repo-root `.env` (backend, not Horizon)      |


---

## Development

```bash
# Backend lint/tests (from repo root)
cd backend && pytest && ruff check .
```

Feature design docs live under `docs/superpowers/specs/`.