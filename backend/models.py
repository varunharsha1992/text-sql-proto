"""Pydantic v2 models for API responses and the unified agent canvas output contract."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, field_validator


# InsightItem — one card/badge on the canvas
class InsightItem(BaseModel):
    type: Literal["stat", "text", "warning", "badge"]
    label: str | None = None  # for type="stat"
    value: str | None = None  # for type="stat"
    content: str | None = None  # for type="text" | "warning" | "badge"
    color: Literal["green", "amber", "red"] | None = None


# ChartSpec — one chart rendered by ChartRenderer.tsx
class ChartSpec(BaseModel):
    type: Literal["bar", "line", "histogram", "scatter", "heatmap", "boxplot"]
    title: str
    x_label: str
    y_label: str
    data: list[dict[str, str | int | float]]  # [{x: ..., y: ...}]


# TableData — tabular results
class TableData(BaseModel):
    columns: list[str]
    rows: list[list[str | int | float | None]]


# ── Data dictionary ──────────────────────────────────────────────────────────
class DataDictionaryEntry(BaseModel):
    column: str
    dtype: str
    semantic_type: Literal[
        "identifier", "categorical", "numeric", "temporal", "currency", "boolean", "text"
    ]
    description: str
    sample_values: list[str]
    null_pct: float
    unit: str | None = None
    is_pii: bool = False


# ── Semantic layer ───────────────────────────────────────────────────────────
class Measure(BaseModel):
    name: str
    column: str
    aggregation: Literal["sum", "avg", "count", "count_distinct", "min", "max", "median"]
    description: str


class Dimension(BaseModel):
    name: str
    column: str
    description: str


class Entity(BaseModel):
    name: str
    description: str
    # Tolerance: the agent occasionally omits this; default to empty rather than reject.
    key_columns: list[str] = []


class SemanticLayer(BaseModel):
    grain: str
    entities: list[Entity]
    measures: list[Measure]
    dimensions: list[Dimension]
    time_dimension: str | None = None
    suggested_questions: list[str]

    @field_validator("time_dimension", mode="before")
    @classmethod
    def _coerce_time_dimension(cls, v: object) -> object:
        """Tolerate the agent emitting an object ({name, column, description});
        reduce it to the column-name string the frontend contract expects."""
        if isinstance(v, dict):
            col = v.get("column") or v.get("name")
            return col if isinstance(col, str) else None
        return v


# ── Progress (streamed agent todos) ──────────────────────────────────────────
class ProgressItem(BaseModel):
    text: str
    status: Literal["pending", "in_progress", "completed"]


# CanvasResponse — the single output contract for ALL agents
class CanvasResponse(BaseModel):
    insights: list[InsightItem]
    charts: list[ChartSpec]
    table: TableData | None = None
    data_dictionary: list[DataDictionaryEntry] | None = None
    semantic_layer: SemanticLayer | None = None


# API response models
class UploadResponse(BaseModel):
    upload_id: str
    job_id: str
    slug: str


class UploadSummary(BaseModel):
    upload_id: str
    slug: str
    filename: str
    row_count: int | None = None
    col_count: int | None = None
    job_id: str | None = None
    status: Literal["pending", "running", "done", "error"] | None = None


class UploadsListResponse(BaseModel):
    uploads: list[UploadSummary]


class JobResponse(BaseModel):
    job_id: str
    status: Literal["pending", "running", "done", "error"]
    result: CanvasResponse | None = None
    error: str | None = None
    progress: list[ProgressItem] | None = None
