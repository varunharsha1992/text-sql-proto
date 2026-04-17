# Text2SQL + EDA Agent — Product & Engineering Spec
**Version:** 1.0  
**Stack:** Next.js 14 · FastAPI · LangGraph · OpenAI GPT-4o · SQLite · Python 3.11  
**Scope:** Live demo build — 4 screens, 4 agents, end-to-end from CSV upload to NL-driven analysis

---

## 1. Overview

A multi-agent data analysis application where a user uploads a messy CSV, an agent understands it semantically, another cleans it intelligently, and a final multi-agent graph answers natural language queries with SQL, charts, and insight summaries. The system is designed to mimic how a senior data scientist and data engineer would collaboratively approach a new dataset — not just run queries, but understand, clean, and reason about data before touching it.

---

## 2. Screen Flow

```
Screen 1: Upload + Auto EDA
    ↓  (on upload complete)
Screen 2: Context Agent — Semantic Catalog Builder
    ↓  (user marks context complete)
Screen 3: Cleanup Agent — Decision Log
    ↓  (cleanup complete)
Screen 4: Query Canvas — Text2SQL + EDA Multi-Agent
```

Navigation is linear but screens remain accessible via top nav. Screens 2–4 are disabled until their prerequisite step completes.

---

## 3. Database Schema (SQLite — `app.db`)

```sql
-- Raw uploaded file metadata
CREATE TABLE uploads (
    id TEXT PRIMARY KEY,
    filename TEXT,
    original_path TEXT,
    uploaded_at DATETIME DEFAULT CURRENT_TIMESTAMP
);

-- Clean data is written as a dynamic table: clean_{upload_id}
-- Raw data is written as: raw_{upload_id}

-- Semantic catalog: one row per column per table
CREATE TABLE catalog (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    upload_id TEXT,
    table_name TEXT,
    column_name TEXT,
    data_type TEXT,
    description TEXT,
    sample_values TEXT,          -- JSON array of 3-5 representative values
    is_primary_key BOOLEAN,
    is_foreign_key BOOLEAN,
    foreign_key_table TEXT,
    foreign_key_column TEXT,
    null_pct REAL,
    cardinality INTEGER,
    inferred_role TEXT,          -- "dimension" | "measure" | "identifier" | "datetime"
    business_context TEXT,       -- from agent Q&A, e.g. "revenue in USD, pre-tax"
    updated_at DATETIME DEFAULT CURRENT_TIMESTAMP
);

-- Context agent conversation history
CREATE TABLE context_conversations (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    upload_id TEXT,
    role TEXT,                   -- "agent" | "user"
    message TEXT,
    timestamp DATETIME DEFAULT CURRENT_TIMESTAMP
);

-- Cleanup decisions log
CREATE TABLE cleanup_log (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    upload_id TEXT,
    column_name TEXT,
    issue_type TEXT,             -- "missing_values" | "duplicates" | "outliers" | "type_mismatch" | "inconsistent_format"
    issue_detail TEXT,           -- e.g. "12.4% nulls detected"
    decision TEXT,               -- "impute" | "drop" | "cap" | "deduplicate" | "reformat" | "skip"
    method TEXT,                 -- e.g. "median imputation" | "IQR 1.5x fence" | "keep first"
    rows_affected INTEGER,
    reasoning TEXT,              -- agent's explanation of why this decision was made
    executed_at DATETIME DEFAULT CURRENT_TIMESTAMP
);

-- Query history for Screen 4
CREATE TABLE query_history (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    upload_id TEXT,
    user_message TEXT,
    agent_type TEXT,             -- "text2sql" | "eda" | "both"
    sql_query TEXT,
    chat_response TEXT,
    canvas_response TEXT,        -- JSON: {insights: [], charts: []}
    timestamp DATETIME DEFAULT CURRENT_TIMESTAMP
);
```

---

## 4. API Endpoints (FastAPI)

```
POST   /api/upload                    → upload CSV, trigger Auto EDA
GET    /api/upload/{id}/status        → polling for EDA completion
GET    /api/upload/{id}/autoeda       → returns auto EDA canvas response

POST   /api/context/{upload_id}/chat  → send user message to Context Agent
GET    /api/context/{upload_id}/catalog → returns full catalog JSON
POST   /api/context/{upload_id}/complete → mark context phase done, trigger Cleanup

GET    /api/cleanup/{upload_id}/status   → polling for cleanup completion
GET    /api/cleanup/{upload_id}/log      → returns cleanup_log rows

POST   /api/query/{upload_id}         → send NL query to Router → agents
GET    /api/query/{upload_id}/history → returns query history
```

All agent endpoints that stream use **Server-Sent Events (SSE)** for the chat side. Canvas response is returned as a final JSON payload at end of stream.

---

## 5. Agent Specifications

---

### 5.1 Auto EDA Agent (Screen 1, triggered on upload)

**Role persona:** *"You are a senior data scientist doing a first-pass exploratory analysis of a new dataset. Your job is to quickly understand the shape, quality, and key distributions of the data before any cleaning or modeling. You produce a structured summary and a set of charts that give the analyst an immediate feel for what they're working with."*

**Trigger:** Fires automatically after CSV is parsed and written to `raw_{upload_id}` SQLite table.

**Tools (4 tools):**

```python
get_dataframe_profile(upload_id: str) -> dict
    # Returns: shape, dtypes, null counts, nunique per column,
    # basic describe() stats. This is the agent's starting context.
    # Reads from raw_{upload_id} SQLite table.

run_python_analysis(upload_id: str, code: str) -> str
    # Executes arbitrary Python (pandas) against raw_{upload_id}.
    # Returns stdout + any exception. Agent uses this for custom
    # distribution checks, correlation, value counts etc.
    # SAFETY: runs in restricted exec scope, no file I/O, no imports
    # beyond pandas/numpy/scipy.

generate_chart_spec(
    chart_type: str,       # "bar" | "line" | "histogram" | "scatter" | "heatmap" | "boxplot"
    title: str,
    x_label: str,
    y_label: str,
    data: list[dict]       # [{x: ..., y: ...}] or [{label, value}]
) -> dict
    # Validates and returns a standardised chart JSON contract.
    # Agent calls this to formalise chart output — does NOT render.

write_autoeda_result(upload_id: str, canvas_response: dict) -> bool
    # Persists the final canvas_response to uploads table.
    # canvas_response shape defined in Section 6.
```

**Predefined analysis rules the agent ALWAYS runs** (via `run_python_analysis`):
1. Row/column count + memory size
2. Null percentage per column — flag any column > 5% nulls
3. Duplicate row count
4. For each numeric column: distribution shape (skew, kurtosis), min/max/mean/median
5. For each categorical column with cardinality < 20: value counts
6. Top 3 pairwise correlations (absolute value) among numeric columns
7. Datetime columns: min/max date range, frequency inference

**Chart selection logic** (agent decides, not hardcoded):
- Numeric column with cardinality > 20 → histogram
- Categorical column with cardinality ≤ 10 → bar chart
- Two numeric columns with |correlation| > 0.5 → scatter
- Datetime + numeric → line chart
- Correlation matrix if ≥ 4 numeric columns → heatmap

**Output:** `canvas_response` (see Section 6). No chat_response — this agent is fully automated.

---

### 5.2 Context Agent (Screen 2 — interactive)

**Role persona:** *"You are a senior data analyst onboarding a new dataset for the first time. Your job is to interview the data owner to build a complete semantic catalog — understanding not just what columns are named, but what they mean, how they relate, what business concepts they represent, and what quirks exist. You ask precise, targeted questions. You never ask more than 2 questions at a time. You update the catalog as you learn."*

**Trigger:** User lands on Screen 2. Agent fires an opening message analysing the raw profile and asking its first questions.

**LangGraph node:** Single agent node with tool-calling loop. Conversation is stateful — full history passed each turn.

**Tools (5 tools):**

```python
get_dataframe_profile(upload_id: str) -> dict
    # Same as Auto EDA. Agent's read-only view of raw data shape.
    # Called once at conversation start to ground the agent.

sample_column_values(upload_id: str, column_name: str, n: int = 10) -> list
    # Returns n random non-null sample values from a column.
    # Agent uses this to ask informed questions:
    # e.g. "I can see values like 'TXN_2024_001' — is this a
    # transaction ID generated by your system?"

infer_relationships(upload_id: str) -> list[dict]
    # Runs heuristic FK detection: finds columns in different
    # tables (or same table) with overlapping value sets.
    # Returns: [{col_a, col_b, overlap_pct, suggested_relation}]
    # Agent uses this to ask: "col 'user_id' in orders appears
    # to match 'id' in users — can you confirm this relationship?"

write_catalog_entry(
    upload_id: str,
    table_name: str,
    column_name: str,
    updates: dict        # any subset of catalog fields
) -> bool
    # Writes/updates a single catalog row in SQLite.
    # Agent calls this after EVERY confirmed piece of information.
    # This is how the right-panel catalog updates in real time.

mark_catalog_complete(upload_id: str) -> bool
    # Agent calls this when it's satisfied it has enough context.
    # Triggers the cleanup phase.
```

**Conversation flow the agent follows:**
1. Opening: Profile the data, identify the most ambiguous columns, ask 2 questions
2. For each user response: update catalog via `write_catalog_entry`, ask next 2 questions
3. After 4–6 exchanges (or when user says "done"): summarise what was learned, call `mark_catalog_complete`
4. Agent never asks about things it can infer confidently (e.g. a column named `created_at` with datetime values — it marks it as a datetime dimension without asking)

**What the catalog captures per column:**
- Human description (from Q&A)
- Business context (unit, currency, source system)
- Inferred role: `dimension` | `measure` | `identifier` | `datetime`
- Primary key: boolean (inferred from uniqueness + naming)
- Foreign key: table + column it maps to (from `infer_relationships` + user confirmation)
- Sample values (stored for Text2SQL agent context)

**Output:** Streams `chat_response` (agent's questions/summaries) per turn. `canvas_response` is the live catalog state — returned after every tool call to `write_catalog_entry`.

---

### 5.3 Cleanup Agent (Screen 3 — automated with log)

**Role persona:** *"You are a senior data engineer preparing a dataset for analytical querying. Your job is to make intelligent, defensible cleaning decisions — not to blindly apply transformations. For every decision, you consider the column's business meaning (from the semantic catalog), the distribution of the data, and the downstream use case (SQL analytics). You document every decision with a clear reason. When in doubt, you err on the side of preservation — it is better to flag and skip than to silently distort data."*

**Trigger:** Called when Context Agent calls `mark_catalog_complete`.

**LangGraph node:** Single automated agent — no user interaction. Runs to completion, writes log, signals done.

**Tools (5 tools):**

```python
get_catalog(upload_id: str, table_name: str = None) -> list[dict]
    # Returns full catalog for this upload. Agent reads this first
    # to understand column semantics before touching the data.

get_column_quality_report(upload_id: str, column_name: str) -> dict
    # Returns for a single column:
    # {null_count, null_pct, duplicate_row_count, outlier_count (IQR),
    #  value_distribution, dtype, min, max, mean, std, skew}
    # Agent calls this per column to get the full picture before deciding.

run_python_cleaning(upload_id: str, code: str) -> dict
    # Executes pandas cleaning code against raw_{upload_id} dataframe.
    # Returns {rows_before, rows_after, columns_modified, preview: df.head(3)}
    # Agent writes cleaning code here. The result is NOT yet persisted —
    # agent inspects the preview and decides whether to commit.

commit_clean_data(upload_id: str) -> bool
    # Writes the final cleaned dataframe to clean_{upload_id} SQLite table.
    # Called ONCE at the end after all cleaning steps are applied.

write_cleanup_log_entry(
    upload_id: str,
    column_name: str,
    issue_type: str,
    issue_detail: str,
    decision: str,
    method: str,
    rows_affected: int,
    reasoning: str
) -> bool
    # Writes one row to cleanup_log. Agent calls this for EVERY decision,
    # including "skip" decisions — the log must be complete and auditable.
```

**Decision menu (agent chooses from this fixed set per issue):**

| Issue Type | Available Decisions | Methods |
|---|---|---|
| missing_values | impute, drop_rows, drop_column, skip | mean, median, mode, forward_fill, constant("Unknown") |
| duplicates | deduplicate, skip | keep_first, keep_last, keep_none |
| outliers | cap, drop_rows, skip | IQR_1.5x, IQR_3x, zscore_3, winsorise_5pct |
| type_mismatch | reformat, drop_rows, skip | coerce_numeric, parse_datetime, strip_whitespace |
| inconsistent_format | standardise, skip | lowercase, title_case, regex_extract |

**Decision logic the agent follows:**
- Identifiers and PKs → never impute, only flag
- Measures (revenue, counts) → prefer median imputation if < 20% null; prefer cap for outliers if column is skewed
- Dimensions (categories) → prefer mode or constant "Unknown" for nulls
- If null_pct > 40% → recommend drop_column, log reasoning
- Duplicates → always deduplicate unless column is an identifier where duplicates are valid (e.g. user_id in a transactions table)
- Outliers → cap preferred over drop for measures; skip for identifiers

**Output:** No chat stream. Returns completion signal. `canvas_response` is the full `cleanup_log` as a structured table + summary card.

---

### 5.4 Query Multi-Agent — LangGraph Graph (Screen 4)

**Architecture:** LangGraph `StateGraph` with 3 nodes: `router`, `text2sql`, `eda`. Router decides which agent(s) run. Both agents can run in sequence if the query needs both.

```
User Query
    ↓
[router_node]
    ├── "sql"  → [text2sql_node] → END
    ├── "eda"  → [eda_node]      → END
    └── "both" → [text2sql_node] → [eda_node] → END
```

**Shared graph state:**
```python
class QueryState(TypedDict):
    upload_id: str
    user_query: str
    route: str                    # "sql" | "eda" | "both"
    sql_query: str | None
    sql_results: list[dict] | None
    chat_response: str
    canvas_response: dict         # {insights: [], charts: [], table: []}
```

---

#### 5.4.1 Router Node

**Not a full LLM agent** — a single LLM call with a structured output prompt.

```
System: "You are a query router for a data analysis system. Given a user's
natural language query, decide which agent should handle it:
- 'sql': user wants specific data retrieval, counts, aggregations, filtering,
  ranking, or comparisons that require precise SQL results
- 'eda': user wants patterns, trends, distributions, correlations, anomalies,
  or open-ended exploration that requires Python analysis and charts
- 'both': user wants specific data AND visual/statistical analysis of that data

Respond with ONLY a JSON object: {\"route\": \"sql|eda|both\", \"reason\": \"...\"}"
```

---

#### 5.4.2 Text2SQL Agent Node

**Role persona:** *"You are a senior analytics engineer who translates business questions into precise, efficient SQL. You always consult the semantic catalog before writing a query. You write SQL that is readable, correctly handles NULLs, uses appropriate aggregations, and never returns more than 500 rows without a LIMIT clause. You verify your query makes sense against the schema before executing."*

**Tools (4 tools):**

```python
get_catalog_summary(upload_id: str) -> str
    # Returns a compact text summary:
    # "Table: clean_{id} | Columns: col1 (measure, revenue USD),
    #  col2 (dimension, region), col3 (identifier, PK: order_id) ..."
    # Agent ALWAYS calls this first before writing any SQL.

get_catalog_detail(upload_id: str, column_name: str) -> dict
    # Returns full catalog entry for a specific column including
    # sample values, business context, FK relationships.
    # Agent calls this when it needs to understand a specific column
    # deeply — e.g. before filtering or joining.

execute_sql(upload_id: str, sql: str) -> dict
    # Runs SQL against clean_{upload_id} SQLite.
    # Returns {columns: [], rows: [], row_count: int, error: str|None}
    # If error → agent must fix the query and retry (max 2 retries).

write_query_result(upload_id: str, sql: str, result: dict) -> bool
    # Persists the executed query + result to query_history.
```

**Output format (agent must return):**
```json
{
  "chat_response": "Here are the top 5 regions by revenue in Q3 2024. The North region leads with $2.4M, significantly ahead of South at $1.8M.",
  "canvas_response": {
    "insights": [],
    "charts": [],
    "table": {
      "columns": ["region", "revenue"],
      "rows": [["North", 2400000], ["South", 1800000]]
    }
  }
}
```

Chat response: concise narrative (2–4 sentences). Canvas: table always present; charts only if agent judges visualisation adds value.

---

#### 5.4.3 EDA Agent Node

**Role persona:** *"You are a senior data scientist conducting exploratory analysis. You write clean, well-commented Python (pandas, numpy, scipy) to find patterns, distributions, correlations, and anomalies. You think like a detective — you don't just compute statistics, you interpret what they mean. You always return both a concise narrative insight and structured chart specs that a frontend can render. When you find something surprising, you say so explicitly."*

**Tools (4 tools):**

```python
get_catalog_summary(upload_id: str) -> str
    # Same as Text2SQL agent. Agent reads this first to understand
    # column roles before writing analysis code.

run_python_analysis(upload_id: str, code: str) -> str
    # Executes pandas/numpy/scipy code against clean_{upload_id}.
    # Returns stdout output as string.
    # Agent uses this for: distributions, correlations, group-by analysis,
    # time series decomposition, outlier detection, statistical tests.
    # Restricted imports: pandas, numpy, scipy.stats, datetime only.

generate_chart_spec(chart_type, title, x_label, y_label, data) -> dict
    # Same contract as Auto EDA agent.
    # EDA agent decides chart type based on analysis results.

get_sql_results(upload_id: str) -> dict | None
    # If router sent "both", this retrieves the SQL result from state.
    # EDA agent uses this as the base dataset for deeper analysis
    # rather than re-querying the full table.
```

**Output format (agent must return):**
```json
{
  "chat_response": "Revenue shows a strong right skew (skew=2.3) — a small number of high-value orders are pulling the mean up significantly. The median order value of $340 is a more reliable central tendency than the mean of $890.",
  "canvas_response": {
    "insights": [
      {"type": "stat", "label": "Median Order Value", "value": "$340"},
      {"type": "stat", "label": "Revenue Skew", "value": "2.3 (right-skewed)"},
      {"type": "text", "content": "Top 5% of orders account for 48% of total revenue"}
    ],
    "charts": [
      {
        "type": "histogram",
        "title": "Order Value Distribution",
        "x_label": "Order Value ($)",
        "y_label": "Frequency",
        "data": [{"x": 0, "y": 234}, {"x": 100, "y": 891}]
      },
      {
        "type": "bar",
        "title": "Revenue by Region",
        "x_label": "Region",
        "y_label": "Total Revenue ($)",
        "data": [{"x": "North", "y": 2400000}]
      }
    ],
    "table": null
  }
}
```

---

## 6. Canvas Response Contract (Frontend Standard)

All agents write to this shared contract. Frontend renders it uniformly across all screens.

```typescript
interface CanvasResponse {
  insights: InsightItem[];
  charts: ChartSpec[];
  table: TableData | null;
}

interface InsightItem {
  type: "stat" | "text" | "warning" | "badge";
  label?: string;      // for type: "stat"
  value?: string;      // for type: "stat"
  content?: string;    // for type: "text" | "warning"
  color?: string;      // optional: "green" | "amber" | "red"
}

interface ChartSpec {
  type: "bar" | "line" | "histogram" | "scatter" | "heatmap" | "boxplot";
  title: string;
  x_label: string;
  y_label: string;
  data: { x: string | number; y: number }[];  // normalised format
}

interface TableData {
  columns: string[];
  rows: (string | number | null)[][];
}
```

---

## 7. Frontend — Screen Specifications

### Screen 1: Upload + Auto EDA
```
┌─────────────────────┬──────────────────────────────────┐
│  LEFT (40%)         │  RIGHT (60%) — Canvas             │
│                     │                                    │
│  Drop zone          │  [Loading state while EDA runs]   │
│  File name          │                                    │
│  Row/col count      │  InsightCards (stat grid)          │
│  Upload progress    │  Charts (histogram, bar, heatmap)  │
│                     │  Data quality warnings             │
│  [→ Go to Context]  │                                    │
└─────────────────────┴──────────────────────────────────┘
```
- "Go to Context" button enabled only after EDA completes
- Canvas uses `CanvasResponse` contract — same renderer as Screen 4

### Screen 2: Context Agent
```
┌─────────────────────┬──────────────────────────────────┐
│  LEFT (40%) — Chat  │  RIGHT (60%) — Catalog Canvas     │
│                     │                                    │
│  Agent messages     │  [Dropdown: source table]          │
│  User input         │                                    │
│  (SSE stream)       │  Catalog table:                    │
│                     │  Column | Type | Role | Description│
│                     │  PK | FK → table.col               │
│  [✓ Mark Complete]  │                                    │
└─────────────────────┴──────────────────────────────────┘
```
- Catalog updates live as agent calls `write_catalog_entry`
- FK entries show as linked badges: `→ orders.user_id`
- "Mark Complete" triggers Cleanup Agent and navigates to Screen 3

### Screen 3: Cleanup Agent
```
┌─────────────────────────────────────────────────────────┐
│  FULL WIDTH                                              │
│                                                          │
│  Summary card: "X issues found across Y columns.        │
│  Z rows affected. Clean data written to SQLite."         │
│                                                          │
│  Decision log table:                                     │
│  Column | Issue | Decision | Method | Rows | Reasoning  │
│                                                          │
│  [Status: Running... / Complete]                         │
│  [→ Go to Query]                                         │
└─────────────────────────────────────────────────────────┘
```
- Polling `/api/cleanup/{id}/status` every 2s while running
- Log rows appear as they are written (polling `/api/cleanup/{id}/log`)
- Decision badges colour-coded: impute=blue, drop=red, cap=amber, skip=grey

### Screen 4: Query + Output
```
┌─────────────────────┬──────────────────────────────────┐
│  LEFT (35%) — Chat  │  RIGHT (65%) — Canvas             │
│                     │                                    │
│  History of turns   │  InsightCards                      │
│  (chat_response)    │  Charts (Recharts)                 │
│                     │  Results table                     │
│  Input box          │                                    │
│  [Route badge:      │  [Export CSV]                      │
│   SQL / EDA / Both] │                                    │
└─────────────────────┴──────────────────────────────────┘
```
- Route badge shown per response (set by router node)
- Canvas replaces on each new query (history accessible via chat scroll)
- SSE streams chat_response; canvas_response delivered as final event

---

## 8. Project File Structure

```
text2sql-eda/
├── backend/
│   ├── main.py                    # FastAPI app, all routes
│   ├── database.py                # SQLite setup, table creation
│   ├── models.py                  # Pydantic request/response models
│   ├── agents/
│   │   ├── auto_eda_agent.py      # AutoEDA LangChain agent
│   │   ├── context_agent.py       # Context LangGraph node + tools
│   │   ├── cleanup_agent.py       # Cleanup LangGraph node + tools
│   │   └── query_graph.py         # LangGraph StateGraph: router + text2sql + eda
│   ├── tools/
│   │   ├── dataframe_tools.py     # get_dataframe_profile, sample_column_values
│   │   ├── catalog_tools.py       # get_catalog, write_catalog_entry, etc.
│   │   ├── python_tools.py        # run_python_analysis, run_python_cleaning
│   │   ├── sql_tools.py           # execute_sql, write_query_result
│   │   └── chart_tools.py         # generate_chart_spec
│   ├── utils/
│   │   ├── csv_parser.py          # Upload → SQLite raw table
│   │   └── heuristics.py          # infer_relationships, outlier detection
│   └── requirements.txt
│
├── frontend/
│   ├── app/
│   │   ├── page.tsx               # Root → redirect to /upload
│   │   ├── upload/page.tsx        # Screen 1
│   │   ├── context/page.tsx       # Screen 2
│   │   ├── cleanup/page.tsx       # Screen 3
│   │   └── query/page.tsx         # Screen 4
│   ├── components/
│   │   ├── Canvas.tsx             # Shared canvas renderer
│   │   ├── ChartRenderer.tsx      # Recharts wrapper for ChartSpec
│   │   ├── InsightCard.tsx        # Stat / text / warning cards
│   │   ├── CatalogTable.tsx       # Screen 2 right panel
│   │   ├── CleanupLog.tsx         # Screen 3 decision table
│   │   ├── ChatPanel.tsx          # Shared SSE chat panel
│   │   └── NavBar.tsx             # Top nav with step progress
│   ├── lib/
│   │   ├── api.ts                 # All fetch wrappers
│   │   └── types.ts               # CanvasResponse, ChartSpec, etc.
│   └── package.json
│
├── data/                          # SQLite db lives here
│   └── app.db
│
├── .cursorrules
└── README.md
```

---

## 9. CursorRules (`.cursorrules`)

```
# Stack
backend: FastAPI, Python 3.11, LangGraph, LangChain, OpenAI GPT-4o, SQLite
frontend: Next.js 14 (app router), TypeScript, Tailwind CSS, Recharts
package_manager: pip (backend), npm (frontend)

# Architecture
- All agents live in backend/agents/. Tools live in backend/tools/.
- Tools are pure Python functions decorated with @tool (LangChain).
- No business logic in main.py — routes call agents only.
- All database writes go through tools — agents never write directly.
- Canvas contract (CanvasResponse) is the only format frontend consumes.
- Agent prompts live as constants at top of each agent file — never inline.

# Code style
- All async functions use async/await — no sync blocking in FastAPI routes.
- All tools must have docstrings describing input, output, and side effects.
- Python: type hints on all function signatures.
- TypeScript: strict mode, no `any`.
- Error handling: tools return error strings, never raise — agents handle errors.

# SQL safety
- Never concatenate user input into SQL strings.
- All execute_sql calls use parameterised queries or LLM-generated SQL only.
- SQL execution is always against clean_{upload_id} — never raw_{upload_id}.

# Agent patterns
- All agent prompts follow role persona → context → constraints → output format.
- Output format must always be specified as JSON in the system prompt.
- LangGraph nodes must update state cleanly — no side effects outside tools.
- Max LLM retries per tool call: 2.

# Never generate
- No print statements in production code (use logging).
- No hardcoded API keys — use environment variables.
- No inline styles in React components — Tailwind classes only.
```

---

## 10. Environment Variables

```
OPENAI_API_KEY=
DATABASE_URL=sqlite:///./data/app.db
UPLOAD_DIR=./data/uploads
MAX_FILE_SIZE_MB=50
PYTHON_REPL_TIMEOUT_SEC=30
```

---

## 11. Demo Data Recommendation

Use a **messy e-commerce orders CSV** with the following intentional issues:
- `revenue` column: 8% nulls, some negative values (outliers), stored as string with "$" prefix
- `customer_id`: 200 duplicate orders
- `region`: mixed case ("north", "North", "NORTH")
- `order_date`: mixed formats ("2024-01-15" and "15/01/2024")
- `product_category`: 3% nulls
- `discount_pct`: 15 rows with values > 100 (data entry errors)

This gives every agent something meaningful to do and every agent decision is explainable to the audience.

---

## 12. Build Order for Live Session

| Step | What | Time |
|---|---|---|
| 1 | Cursor setup: clone scaffold, set .cursorrules, install deps | 5 min |
| 2 | `database.py` — all table schemas | 5 min |
| 3 | `csv_parser.py` + `POST /api/upload` route | 5 min |
| 4 | `dataframe_tools.py` + `python_tools.py` | 5 min |
| 5 | `auto_eda_agent.py` + `GET /api/upload/{id}/autoeda` | 10 min |
| 6 | `catalog_tools.py` + `context_agent.py` | 10 min |
| 7 | `cleanup_agent.py` | 10 min |
| 8 | `query_graph.py` (router + text2sql + eda nodes) | 10 min |
| 9 | Frontend: Screen 1 + Canvas component + ChartRenderer | 10 min |
| 10 | Frontend: Screens 2, 3, 4 wired to backend | 10 min |

**Total: ~80 min.** For a 60-min session, defer Screen 3 frontend polish and show cleanup log as raw JSON — the agents are the story, not the UI.
