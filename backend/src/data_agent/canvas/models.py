"""Canvas asset contracts (ChartAsset / params / output schema / gate / replay)."""

from __future__ import annotations

from datetime import UTC, datetime
from enum import StrEnum
from typing import Any, Literal
from uuid import uuid4

from pydantic import BaseModel, Field

from ..catalog.models import DatasetRef


def _now() -> str:
    return datetime.now(UTC).isoformat()


def new_asset_id() -> str:
    return "ca_" + uuid4().hex


class AssetStatus(StrEnum):
    draft = "draft"
    validated = "validated"
    on_canvas = "on_canvas"
    broken = "broken"


class ParamAffects(StrEnum):
    data = "data"  # changes RenderData -> needs replay (backend)
    appearance = "appearance"  # only ChartConfig.appearance -> local re-render


class ParamField(BaseModel):
    key: str
    label: str
    type: Literal["int", "float", "str", "bool", "date", "select", "multiselect", "column_ref"]
    default: Any = None
    min: float | int | None = None
    max: float | int | None = None
    options: list[Any] | None = None
    dataset_ref: DatasetRef | None = None  # column_ref: choices come from this dataset
    affects: ParamAffects = ParamAffects.data


class DataSourceBinding(BaseModel):
    alias: str  # ctx.data[alias]
    dataset: DatasetRef


class OutputField(BaseModel):
    name: str
    dtype: str  # dtype family: int|float|str|date|datetime|bool


class OutputTable(BaseModel):
    name: str = "main"
    columns: list[OutputField]
    min_rows: int = 0
    max_rows: int = 100_000


class OutputSchema(BaseModel):
    tables: list[OutputTable] = Field(default_factory=list)


class Placement(BaseModel):
    x: int = 0
    y: int = 0
    w: int = 6  # 12-col grid
    h: int = 4
    z: int = 0


class ProvenanceInfo(BaseModel):
    created_by: Literal["user", "ai", "promote"] = "user"
    session_id: str | None = None
    adhoc_id: str | None = None
    source_run_id: str | None = None


class GateCheck(BaseModel):
    kind: Literal["columns", "dtypes", "row_bounds", "payload", "timeout", "exec"]
    expected: str = ""
    actual: str = ""
    passed: bool
    detail: str | None = None


class GateReport(BaseModel):
    asset_id: str
    version: int
    passed: bool
    checks: list[GateCheck] = Field(default_factory=list)
    errors: list[str] = Field(default_factory=list)  # structured hints for a fixer
    elapsed_s: float = 0.0
    ran_at: str = ""
    kernel: Literal["clean"] = "clean"


class ChartAsset(BaseModel):
    id: str = Field(default_factory=new_asset_id)
    name: str
    status: AssetStatus = AssetStatus.draft
    version: int = 1
    bindings: list[DataSourceBinding] = Field(default_factory=list)
    param_spec: list[ParamField] = Field(default_factory=list)
    params: dict[str, Any] = Field(default_factory=dict)
    output_schema: OutputSchema | None = None
    chart_type: str = "bar"
    placement: Placement = Field(default_factory=Placement)
    processor_hash: str = ""
    params_hash: str = ""
    provenance: ProvenanceInfo = Field(default_factory=ProvenanceInfo)
    last_gate: GateReport | None = None
    description: str = ""
    created_at: str = Field(default_factory=_now)
    updated_at: str = Field(default_factory=_now)

    def touch(self) -> None:
        self.updated_at = _now()


class ReplayResult(BaseModel):
    gate: GateReport
    render: dict[str, Any] | None = None
    config: dict[str, Any] | None = None
    version: int
    notes: list[str] = Field(default_factory=list)  # ctx.log lines


class AssetIndexRow(BaseModel):
    """GET /api/assets cold-load shape: no payload bodies, lazy /render per card."""

    id: str
    name: str
    status: AssetStatus
    version: int
    chart_type: str
    placement: Placement
    gate_passed: bool | None = None
    gate_at: str | None = None
    has_render: bool = False
