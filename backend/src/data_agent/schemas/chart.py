"""Render pair contract (frozen at N2 end; design-architecture §2.6).

Frontend ECharts consumes (RenderData, ChartConfig):
  - RenderData: columnar tables, JSON-safe, addressed as "<table>.<column>"
  - ChartConfig: pure JSON — chart_type whitelist, option_template overrides,
    data_map channel->column bindings, appearance knobs (height/width/font/palette)
Processors return these models from inside the kernel (same venv => importable).
"""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field

CHART_TYPES = ("bar", "line", "pie", "scatter", "histogram", "box", "heatmap", "area")
ChartType = Literal["bar", "line", "pie", "scatter", "histogram", "box", "heatmap", "area"]


class RenderColumn(BaseModel):
    name: str
    dtype: str  # "int" | "float" | "str" | "date" | "datetime" | "bool"
    values: list[Any]  # nulls as None


class RenderTable(BaseModel):
    dimensions: list[str]  # column order == RenderColumn order
    source: list[RenderColumn]

    def column(self, name: str) -> RenderColumn | None:
        return next((c for c in self.source if c.name == name), None)


class RenderData(BaseModel):
    tables: dict[str, RenderTable] = Field(default_factory=dict)
    row_count: int = 0
    payload_bytes: int = 0

    def with_defaults(self) -> RenderData:
        """Fill row_count/payload_bytes if the processor left them unset."""
        if not self.tables:
            return self
        if not self.row_count:
            main = self.tables.get("main") or next(iter(self.tables.values()))
            self.row_count = len(main.source[0].values) if main.source else 0
        if not self.payload_bytes:
            self.payload_bytes = len(self.model_dump_json().encode("utf-8"))
        return self


class Appearance(BaseModel):
    height: int = Field(default=320, ge=80, le=4000)
    width: int | None = Field(default=None, ge=120, le=6000)  # None = fill card
    font_size: int = Field(default=12, ge=8, le=32)
    color_palette: list[str] | None = None
    show_legend: bool = True
    show_label: bool = False


class DataMap(BaseModel):
    # channel -> "<table>.<column>"; channels are chart_type-specific (x/y/name/value/
    # series.<key>/color/size/values...). Free dict on purpose; renderer validates.
    map: dict[str, str] = Field(default_factory=dict)


class ChartConfig(BaseModel):
    chart_type: ChartType
    title: str = ""
    option_template: dict[str, Any] = Field(default_factory=dict)  # pure-JSON overrides
    data_map: DataMap = Field(default_factory=DataMap)
    appearance: Appearance = Field(default_factory=Appearance)


class ChartSpecError(ValueError):
    pass


def assert_json_safe(value: Any, *, path: str = "$") -> None:
    """Injection guard: reject function-ish strings inside option_template/config."""
    if isinstance(value, str):
        lowered = value.lower()
        for bad in ("function", "=>", "javascript:", "eval(", "new function"):
            if bad in lowered:
                raise ChartSpecError(f"forbidden token {bad!r} in string at {path}")
    elif isinstance(value, dict):
        for k, v in value.items():
            assert_json_safe(v, path=f"{path}.{k}")
    elif isinstance(value, list):
        for i, v in enumerate(value):
            assert_json_safe(v, path=f"{path}[{i}]")
