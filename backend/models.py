"""Pydantic v2 models for API responses and the unified agent canvas output contract."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel


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


# CanvasResponse — the single output contract for ALL agents
class CanvasResponse(BaseModel):
    insights: list[InsightItem]
    charts: list[ChartSpec]
    table: TableData | None = None


# API response models
class UploadResponse(BaseModel):
    upload_id: str
    job_id: str
    slug: str


class JobResponse(BaseModel):
    job_id: str
    status: Literal["pending", "running", "done", "error"]
    result: CanvasResponse | None = None
    error: str | None = None
