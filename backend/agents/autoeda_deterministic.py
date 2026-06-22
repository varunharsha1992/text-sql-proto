"""Deterministic AutoEDA — one pandas pass, no LLM, no LangGraph tool loop (fast, bounded)."""

from __future__ import annotations

import logging
from typing import Any

import numpy as np
import pandas as pd

from backend.tools.chart import build_chart_spec_dict
from backend.tools.dataframe import load_upload_dataframe_sync

logger = logging.getLogger(__name__)

MAX_CHARTS = 5
HIST_BINS = 20
SCATTER_MAX_POINTS = 800
LINE_MAX_POINTS = 250
HEATMAP_MAX_COLS = 12


def _fmt_int(n: int) -> str:
    return f"{n:,}"


def _mem_mb(df: pd.DataFrame) -> str:
    return f"{df.memory_usage(deep=True).sum() / (1024 * 1024):.1f} MB"


def _numeric_cols(df: pd.DataFrame) -> list[str]:
    return [c for c in df.columns if pd.api.types.is_numeric_dtype(df[c])]


def _datetime_cols(df: pd.DataFrame) -> list[str]:
    out: list[str] = []
    for c in df.columns:
        s = df[c]
        if pd.api.types.is_datetime64_any_dtype(s):
            out.append(c)
        elif pd.api.types.is_object_dtype(s) or pd.api.types.is_string_dtype(s):
            ser = s.dropna()
            if len(ser) == 0:
                continue
            parsed = pd.to_datetime(ser, errors="coerce")
            ratio = float(parsed.notna().sum()) / float(len(ser))
            if ratio >= 0.72:
                out.append(c)
    return out


def _date_range_value(df: pd.DataFrame, dcol: str) -> str | None:
    """Return "min → max" date range for a column, or None if unparseable/empty."""
    s = pd.to_datetime(df[dcol], errors="coerce").dropna()
    if len(s) == 0:
        return None
    return f"{s.min().date()} → {s.max().date()}"


def _outlier_warnings(df: pd.DataFrame, num_cols: list[str]) -> list[dict[str, Any]]:
    """Surface likely data-entry errors and extreme outliers in numeric columns.

    Spec US2 AC#3: a numeric column with values that look like data entry errors
    (e.g. percentages >100) must be flagged. We check two cases:
      1. Percentage-like columns with values outside the 0–100 range.
      2. Far outliers (beyond 3×IQR) affecting at least 1% of non-null values.
    """
    warnings: list[dict[str, Any]] = []
    for col in num_cols:
        s = df[col].dropna()
        if len(s) < 4:
            continue
        name = str(col).lower()
        is_pct = (
            "pct" in name
            or "percent" in name
            or "%" in name
            or name.endswith("_rate")
        )
        if is_pct:
            bad = int(((s > 100) | (s < 0)).sum())
            if bad > 0:
                warnings.append(
                    {
                        "type": "warning",
                        "content": (
                            f"{col}: {bad} value(s) outside the 0–100% range "
                            f"(possible data entry errors)"
                        ),
                        "color": "amber",
                    }
                )
                continue  # don't double-report the same column via IQR

        q1 = float(s.quantile(0.25))
        q3 = float(s.quantile(0.75))
        iqr = q3 - q1
        if iqr <= 0:
            continue
        lo = q1 - 3.0 * iqr
        hi = q3 + 3.0 * iqr
        n_out = int(((s < lo) | (s > hi)).sum())
        if n_out > 0 and (n_out / len(s)) * 100.0 >= 1.0:
            warnings.append(
                {
                    "type": "warning",
                    "content": (
                        f"{col}: {n_out} extreme outlier(s) detected "
                        f"(range {s.min():.0f}–{s.max():.0f})"
                    ),
                    "color": "amber",
                }
            )
    return warnings


def _append_chart(charts: list[dict[str, Any]], **kwargs: Any) -> None:
    if len(charts) >= MAX_CHARTS:
        return
    spec = build_chart_spec_dict(
        kwargs["chart_type"],
        kwargs["title"],
        kwargs["x_label"],
        kwargs["y_label"],
        kwargs["data"],
    )
    if "error" not in spec:
        charts.append(spec)


def build_autoeda_canvas_sync(upload_id: str) -> dict[str, Any]:
    """Build CanvasResponse dict: stats, null warnings, duplicate stat, up to 5 charts."""
    df = load_upload_dataframe_sync(upload_id)
    insights: list[dict[str, Any]] = []
    charts: list[dict[str, Any]] = []

    if df.empty or len(df.columns) == 0:
        insights.append({"type": "text", "content": "No rows or columns to analyse."})
        return {"insights": insights, "charts": [], "table": None}

    rows, cols = df.shape
    dup_n = int(df.duplicated().sum())
    null_cells = int(df.isna().sum().sum())
    num_cols = _numeric_cols(df)
    dt_cols = _datetime_cols(df)

    # --- Stat cards (spec FR-006: rows, null cells, duplicates, date range) ---
    insights.append({"type": "stat", "label": "Rows", "value": _fmt_int(rows)})
    insights.append({"type": "stat", "label": "Columns", "value": str(cols)})
    null_stat: dict[str, Any] = {
        "type": "stat",
        "label": "Null cells",
        "value": _fmt_int(null_cells),
    }
    if null_cells > 0:
        null_stat["color"] = "amber"
    insights.append(null_stat)
    if dup_n > 0:
        insights.append(
            {"type": "stat", "label": "Duplicates", "value": _fmt_int(dup_n), "color": "amber"}
        )
    else:
        insights.append({"type": "stat", "label": "Duplicates", "value": "0"})

    # Date range stat card — first parseable datetime column (if any)
    for dcol in dt_cols:
        dr = _date_range_value(df, dcol)
        if dr is not None:
            insights.append({"type": "stat", "label": f"{dcol} range", "value": dr})
            break

    insights.append({"type": "stat", "label": "Est. size", "value": _mem_mb(df)})

    # --- Quality warnings: per-column nulls (>5%) then outliers -----------
    for col in df.columns:
        null_n = int(df[col].isna().sum())
        pct = (null_n / rows) * 100.0 if rows else 0.0
        if pct > 5.0:
            insights.append(
                {
                    "type": "warning",
                    "content": f"{col}: {pct:.1f}% null values",
                }
            )

    insights.extend(_outlier_warnings(df, num_cols))

    # --- Charts (priority order, max 5) ---------------------------------
    # 1) Correlation heatmap if enough numeric columns
    if len(num_cols) >= 4:
        sub = num_cols[:HEATMAP_MAX_COLS]
        corr = df[sub].corr(numeric_only=True)
        heat_data: list[dict[str, str | int | float]] = []
        for ri in corr.index:
            for cj in corr.columns:
                heat_data.append(
                    {
                        "x": str(cj),
                        "y": str(ri),
                        "value": float(corr.loc[ri, cj]),
                    }
                )
        _append_chart(
            charts,
            chart_type="heatmap",
            title="Numeric correlations",
            x_label="Column",
            y_label="Column",
            data=heat_data,
        )

    # 2) Histograms: numeric columns with many distinct values
    for col in num_cols:
        if len(charts) >= MAX_CHARTS:
            break
        nu = int(df[col].nunique(dropna=True))
        if nu <= 20:
            continue
        series = df[col].dropna()
        if len(series) < 2:
            continue
        counts, edges = np.histogram(series.astype(float), bins=HIST_BINS)
        data_pts: list[dict[str, str | int | float]] = []
        for i in range(len(counts)):
            mid = float((edges[i] + edges[i + 1]) / 2.0)
            data_pts.append({"x": mid, "y": int(counts[i])})
        _append_chart(
            charts,
            chart_type="histogram",
            title=f"{col} distribution",
            x_label=str(col),
            y_label="Count",
            data=data_pts,
        )

    # 3) Bar charts: low-cardinality non-numeric (or low-cardinality object)
    for col in df.columns:
        if len(charts) >= MAX_CHARTS:
            break
        if col in num_cols and df[col].nunique(dropna=True) > 10:
            continue
        nu = int(df[col].nunique(dropna=True))
        if nu < 1 or nu > 10:
            continue
        vc = df[col].value_counts().head(10)
        bar_data: list[dict[str, str | int | float]] = [
            {"x": str(idx), "y": int(v)} for idx, v in vc.items()
        ]
        if not bar_data:
            continue
        _append_chart(
            charts,
            chart_type="bar",
            title=f"{col} (top categories)",
            x_label=str(col),
            y_label="Count",
            data=bar_data,
        )

    # 4) Scatter: strongest |r| > 0.5 among numeric pairs
    if len(num_cols) >= 2:
        corr_full = df[num_cols].corr(numeric_only=True)
        pairs: list[tuple[str, str, float]] = []
        for i, a in enumerate(num_cols):
            for b in num_cols[i + 1 :]:
                v = float(corr_full.loc[a, b])
                if not np.isnan(v) and abs(v) > 0.5:
                    pairs.append((a, b, v))
        pairs.sort(key=lambda t: -abs(t[2]))
        for a, b, _ in pairs[:2]:
            if len(charts) >= MAX_CHARTS:
                break
            sub_df = df[[a, b]].dropna()
            if len(sub_df) == 0:
                continue
            if len(sub_df) > SCATTER_MAX_POINTS:
                sub_df = sub_df.sample(SCATTER_MAX_POINTS, random_state=42)
            scat: list[dict[str, str | int | float]] = [
                {"x": float(r[a]), "y": float(r[b])} for _, r in sub_df.iterrows()
            ]
            _append_chart(
                charts,
                chart_type="scatter",
                title=f"{a} vs {b}",
                x_label=str(a),
                y_label=str(b),
                data=scat,
            )

    # 5) Line: first parsed datetime vs first numeric
    if dt_cols and num_cols and len(charts) < MAX_CHARTS:
        dcol = dt_cols[0]
        ncol = num_cols[0]
        tmp = df[[dcol, ncol]].copy()
        tmp[dcol] = pd.to_datetime(tmp[dcol], errors="coerce")
        tmp = tmp.dropna(subset=[dcol, ncol]).sort_values(dcol)
        if len(tmp) > 1:
            if len(tmp) > LINE_MAX_POINTS:
                n = min(LINE_MAX_POINTS, len(tmp))
                idx = np.linspace(0, len(tmp) - 1, n, dtype=int)
                tmp = tmp.iloc[idx]
            line_pts: list[dict[str, str | int | float]] = []
            for _, row in tmp.iterrows():
                dval = row[dcol]
                nval = float(row[ncol])
                ts = pd.Timestamp(dval)
                xs = str(ts.date()) if pd.notna(ts) else str(dval)
                line_pts.append({"x": xs, "y": nval})
            _append_chart(
                charts,
                chart_type="line",
                title=f"{ncol} over {dcol}",
                x_label=str(dcol),
                y_label=str(ncol),
                data=line_pts,
            )

    # One compact text insight: top correlations (numeric)
    if len(num_cols) >= 2:
        corr_full = df[num_cols].corr(numeric_only=True)
        triples: list[tuple[str, str, float]] = []
        for i, a in enumerate(num_cols):
            for b in num_cols[i + 1 :]:
                v = float(corr_full.loc[a, b])
                if not np.isnan(v):
                    triples.append((a, b, v))
        triples.sort(key=lambda t: -abs(t[2]))
        top = triples[:3]
        if top:
            parts = [f"{a}↔{b}: r={v:.2f}" for a, b, v in top]
            insights.append({"type": "text", "content": "Top correlations — " + "; ".join(parts)})

    logger.info(
        "Deterministic AutoEDA done upload_id=%s rows=%s charts=%s insights=%s",
        upload_id,
        rows,
        len(charts),
        len(insights),
    )
    return {"insights": insights, "charts": charts, "table": None}
