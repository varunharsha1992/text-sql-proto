"""ChartSpec validation — shared by the generate_chart_spec tool and deterministic AutoEDA."""

from __future__ import annotations

from langchain_core.tools import tool

_ALLOWED_CHART_TYPES = {"bar", "line", "histogram", "scatter", "heatmap", "boxplot"}


def normalize_chart_data(data: list[dict]) -> list[dict[str, str | int | float]]:
    """Map common LLM key aliases (label/value, name/value) to ChartSpec x/y."""
    out: list[dict[str, str | int | float]] = []
    for item in data:
        if not isinstance(item, dict):
            continue
        if "x" in item and "y" in item:
            out.append({"x": item["x"], "y": item["y"]})
            continue
        x = item.get("label") or item.get("name") or item.get("category")
        y = item.get("value")
        if x is not None and y is not None:
            out.append({"x": x, "y": y})
        else:
            out.append(item)
    return out


def build_chart_spec_dict(
    chart_type: str,
    title: str,
    x_label: str,
    y_label: str,
    data: list[dict[str, str | int | float]],
) -> dict:
    """Return a valid ChartSpec dict, or `{\"error\": ...}` if validation fails."""
    if chart_type not in _ALLOWED_CHART_TYPES:
        return {
            "error": (
                f"Invalid chart_type '{chart_type}'. "
                f"Must be one of: {', '.join(sorted(_ALLOWED_CHART_TYPES))}."
            )
        }

    if not isinstance(data, list) or len(data) == 0:
        return {"error": "data must be a non-empty list of dicts."}

    if not all(isinstance(item, dict) for item in data):
        return {"error": "Every item in data must be a dict."}

    data = normalize_chart_data(data)

    if len(data) > 1:
        first_keys = set(data[0].keys())
        inconsistent = [i for i, item in enumerate(data[1:], start=1) if set(item.keys()) != first_keys]
        if inconsistent:
            return {
                "error": (
                    f"Inconsistent keys in data at indices {inconsistent}. "
                    f"All dicts must share the same keys."
                )
            }

    return {
        "type": chart_type,
        "title": title,
        "x_label": x_label,
        "y_label": y_label,
        "data": data,
    }


@tool
def generate_chart_spec(
    chart_type: str,
    title: str,
    x_label: str,
    y_label: str,
    data: list[dict[str, str | int | float]],
) -> dict:
    """Validates and returns a standardised ChartSpec dict.
    chart_type must be one of: bar, line, histogram, scatter, heatmap, boxplot.
    data must be a list of dicts. Returns dict or {\"error\": ...}.
    """
    return build_chart_spec_dict(chart_type, title, x_label, y_label, data)
