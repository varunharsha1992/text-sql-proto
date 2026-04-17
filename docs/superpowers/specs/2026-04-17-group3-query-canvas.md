# Group 3 — Query Canvas
**Date:** 2026-04-17  
**Approach:** Spec-faithful, must-have/nice-to-have split  
**Demo moment:** User types a business question. A route badge shows SQL / EDA / Both. The canvas updates with a narrative, charts, and/or a results table. SQL is shown in a collapsible block.

---

## Scope

### Must-haves
- Screen 3 split layout: left = chat history + input, right = canvas
- LangGraph supervisor + `Command`-based routing to Text2SQL or EDA node
- Route badge per response (SQL / EDA / Both) shown in chat history
- Text2SQL agent: catalog summary → SQL → execute → table + optional chart + narrative
- EDA agent: catalog summary → Python analysis → insights + charts + narrative
- SQL shown in collapsible code block beneath each chat response
- Canvas replaces on each new query; previous responses in chat scroll
- Loading state on canvas while agents run
- Query history persisted in SQLite

### Nice-to-haves (only if time allows)
- Suggested starter queries generated from catalog on page load
- "Export CSV" button on table results
- Query history survives page refresh (loaded via `GET /api/query/{id}/history`)

---

## LangGraph Architecture — Supervisor + Command Routing

**Pattern:** LangGraph `StateGraph` with 3 nodes. Supervisor uses `Command` to route. For the "both" path, `text2sql` runs first and passes results through state to `eda`.

```
User Query
    ↓
[supervisor_node]
    ├── Command(goto="text2sql") — route: "sql"
    ├── Command(goto="eda")      — route: "eda"
    └── Command(goto="text2sql") — route: "both" (text2sql → eda in sequence)

[text2sql_node]
    ├── route="sql"  → Command(goto=END)
    └── route="both" → Command(goto="eda")

[eda_node] → Command(goto=END)
```

### Shared Graph State

```python
class QueryState(TypedDict):
    upload_id: str
    user_query: str
    route: str                     # "sql" | "eda" | "both" — set by supervisor
    route_reason: str              # supervisor's reasoning (shown in badge tooltip)
    sql_query: str | None          # set by text2sql node
    sql_results: list[dict] | None # set by text2sql node, read by eda node in "both"
    chat_response: str             # accumulated across nodes
    canvas_response: dict          # final CanvasResponse
```

---

## Supervisor Node

**Not a full agent** — a single structured LLM call. Returns `Command` to route.

### Routing Prompt

```
System: "You are a query router for a data analysis system. Given a natural language query, decide which specialist to invoke:

- 'sql': user wants specific data retrieval, counts, aggregations, filtering,
  ranking, comparisons, or anything requiring precise tabular results
- 'eda': user wants patterns, trends, distributions, correlations, anomalies,
  or open-ended exploration requiring statistical analysis and charts
- 'both': user wants specific data AND wants to understand patterns or
  visualise that data in depth

Respond with ONLY valid JSON: {\"route\": \"sql|eda|both\", \"reason\": \"one sentence\"}"
```

### Implementation

```python
from langgraph.types import Command

def supervisor_node(state: QueryState) -> Command:
    response = llm.invoke(supervisor_prompt + state["user_query"])
    parsed = json.loads(response.content)
    return Command(
        goto=parsed["route"] if parsed["route"] != "both" else "text2sql",
        update={"route": parsed["route"], "route_reason": parsed["reason"]}
    )
```

---

## Text2SQL Agent Node

### Role Persona
> "You are a senior analytics engineer who translates business questions into precise, efficient SQL. You always consult the semantic catalog before writing a query. You write SQL that handles NULLs correctly, uses appropriate aggregations, and never returns more than 500 rows without a LIMIT clause. You verify your query makes sense against the schema before executing. If a query fails, you fix it and retry — maximum 2 retries."

### Tools

```python
get_catalog_summary(upload_id: str) -> str
    # Returns compact text: "Table: raw_{id} | Columns: revenue (measure, USD),
    # region (dimension), order_id (identifier, PK), order_date (datetime) ..."
    # Agent ALWAYS calls this first before writing any SQL.

get_catalog_detail(upload_id: str, column_name: str) -> dict
    # Returns full catalog entry for a column: business_context,
    # sample_values, FK relationships, null_pct.
    # Agent calls this when it needs to deeply understand a column
    # before filtering or joining on it.

execute_sql(upload_id: str, sql: str) -> dict
    # Runs SQL against raw_{upload_id} SQLite.
    # Returns { columns: [], rows: [], row_count: int, error: str | None }
    # Hard LIMIT 500 enforced if absent from query.
    # On error: agent must fix and retry (max 2 retries).
    # On 2nd failure: return { error: "Could not execute query" }

write_query_result(upload_id: str, sql: str, result: dict) -> bool
    # Persists query + result to query_history table.
```

### Output Format

```python
# Agent must return structured output matching this shape:
{
  "chat_response": "North leads Q4 with $2.4M revenue — 33% ahead of the next region.",
  "canvas_response": {
    "insights": [],
    "charts": [
      {
        "type": "bar",
        "title": "Revenue by Region — Q4",
        "x_label": "Region",
        "y_label": "Revenue ($)",
        "data": [{"x": "North", "y": 2400000}, {"x": "South", "y": 1800000}]
      }
    ],
    "table": {
      "columns": ["region", "revenue"],
      "rows": [["North", 2400000], ["South", 1800000]]
    }
  },
  "sql_query": "SELECT region, SUM(revenue) FROM raw_... GROUP BY region ..."
}
```

Chart is included only if the agent judges visualisation adds value. Table is always present for SQL results.

---

## EDA Agent Node

### Role Persona
> "You are a senior data scientist conducting exploratory analysis. You write clean Python (pandas, numpy, scipy.stats) to find patterns, distributions, correlations, and anomalies. You think like a detective — you don't just compute statistics, you interpret what they mean. When you find something surprising, you say so explicitly. You always return both a concise narrative and structured chart specs."

### Tools

```python
get_catalog_summary(upload_id: str) -> str
    # Same as Text2SQL node. Always called first.

run_python_analysis(upload_id: str, code: str) -> str
    # Executes pandas/numpy/scipy.stats code against raw_{upload_id}.
    # Returns stdout as string.
    # Restricted imports: pandas, numpy, scipy.stats, datetime only.
    # Timeout: 30s.

generate_chart_spec(chart_type, title, x_label, y_label, data) -> dict
    # Same contract as Group 1. Validates and returns ChartSpec JSON.

get_sql_results(upload_id: str) -> dict | None
    # When route="both": retrieves SQL results from graph state.
    # EDA agent uses this as base dataset for deeper analysis
    # rather than re-querying the full table.
    # Returns None when route="eda" (agent queries full table instead).
```

### Output Format

```python
{
  "chat_response": "Revenue is strongly right-skewed (skew=2.3). A small number of high-value orders pull the mean well above the median. The top 5% of orders account for 48% of total revenue.",
  "canvas_response": {
    "insights": [
      { "type": "stat", "label": "Median Order Value", "value": "$340" },
      { "type": "stat", "label": "Revenue Skew", "value": "2.3 (right)" },
      { "type": "text", "content": "Top 5% of orders = 48% of total revenue" }
    ],
    "charts": [
      {
        "type": "histogram",
        "title": "Order Value Distribution",
        "x_label": "Order Value ($)",
        "y_label": "Frequency",
        "data": [{"x": 0, "y": 234}, {"x": 100, "y": 891}]
      }
    ],
    "table": null
  }
}
```

---

## State Merging for "both" Route

When `route = "both"`, Text2SQL runs first and writes its output to state. EDA node reads `sql_results` from state and builds on top of the SQL data. The final response merges both:

```python
# In the graph's final output assembly:
final_chat = text2sql_chat + "\n\n" + eda_chat
final_canvas = {
  "insights": eda_canvas["insights"],
  "charts": text2sql_canvas["charts"] + eda_canvas["charts"],
  "table": text2sql_canvas["table"]   # always from SQL node
}
```

---

## API Endpoints

```
POST /api/query/{upload_id}
  Body: { message: string }
  Response: {
    chat: string,
    canvas: CanvasResponse,
    route: "sql" | "eda" | "both",
    route_reason: string,
    sql_query: string | null
  }
  Side effects:
    - Runs LangGraph query_graph.invoke() synchronously
    - Writes row to query_history

GET /api/query/{upload_id}/history
  Response: [ ...query_history rows... ]
  Used by: Screen 3 initial load (restores prior session)
```

### FastAPI Implementation (simplified)

```python
@app.post("/api/query/{upload_id}")
async def run_query(upload_id: str, body: QueryRequest):
    result = await query_graph.ainvoke({
        "upload_id": upload_id,
        "user_query": body.message,
        "route": None,
        "sql_query": None,
        "sql_results": None,
        "chat_response": "",
        "canvas_response": {}
    })
    return {
        "chat": result["chat_response"],
        "canvas": result["canvas_response"],
        "route": result["route"],
        "route_reason": result["route_reason"],
        "sql_query": result["sql_query"]
    }
```

---

## Frontend — Screen 3

### Layout

```
┌─────────────────────┬──────────────────────────────────┐
│  LEFT (35%) — Chat  │  RIGHT (65%) — Canvas             │
│                     │                                    │
│  Query history      │  InsightCards                      │
│  (chat_response     │  Charts (Recharts)                 │
│   per turn, with    │  Results table                     │
│   route badge)      │                                    │
│                     │  [Loading skeleton while running]  │
│  SQL code block     │                                    │
│  (collapsible,      │                                    │
│   per turn)         │                                    │
│                     │                                    │
│  Input box          │                                    │
└─────────────────────┴──────────────────────────────────┘
```

### Route Badge

Each chat turn in the left panel shows a coloured badge:
- `SQL` — blue
- `EDA` — purple  
- `Both` — green

Badge has a tooltip showing `route_reason` from the supervisor.

### SQL Code Block

Below each chat response (when `sql_query` is not null), a collapsible `<details>` block shows the SQL with syntax highlighting. Collapsed by default.

### Component Tree

```
query/page.tsx
├── NavBar (step 3 active)
├── ChatPanel (left)
│   ├── QueryTurnList
│   │   └── QueryTurn (chat + route badge + SQL code block)
│   └── InputBox (disabled while running)
└── Canvas (right)
    ├── InsightCards
    ├── ChartRenderer
    └── ResultsTable
```

### State Flow

1. Page loads → `GET /api/query/{uploadId}/history` → restore prior turns in chat
2. User types query → POST → show canvas loading skeleton
3. Response: render chat turn with route badge + SQL block on left; replace canvas on right
4. Repeat for each query

### Chat Turn Hook

```typescript
// lib/hooks.ts
function useChatTurn(uploadId: string) {
  // POSTs to /api/query/{uploadId}
  // returns { send(msg), turns, canvas, loading }
}
```

---

## Safety Constraints

| Constraint | Rule |
|---|---|
| SQL injection | Only LLM-generated SQL — no user input concatenated into queries |
| Result size | Hard `LIMIT 500` appended if absent from generated SQL |
| Python sandbox | Restricted to pandas, numpy, scipy.stats imports only |
| Python timeout | 30s execution timeout via `PYTHON_REPL_TIMEOUT_SEC` |
| LLM retries | Max 2 retries per SQL error before returning friendly error message |
| Data source | All queries run against `raw_{upload_id}` — never the uploads or catalog tables |
