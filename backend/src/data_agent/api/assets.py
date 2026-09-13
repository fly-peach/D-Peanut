"""Canvas assets REST (design-architecture §3.1 canvas plane: sync, no SSE, zero AI).

Gate failures are 200 + passed:false (the screen keeps the previous render);
4xx is reserved for operational errors (missing asset, version conflict, bad body).
"""

from __future__ import annotations

from typing import Any, Literal

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, Field

from ..canvas.assets import AssetNotFound, ConflictError, DuplicateAssetName
from ..canvas.models import ChartAsset, DataSourceBinding, ParamField, Placement
from ..canvas.params import merge_defaults, validate_params
from ..canvas.sourcecheck import check_processor_source, extract_literals
from ..catalog.registry import NotFoundError as DatasetNotFound

router = APIRouter(prefix="/assets", tags=["assets"])


class BindingBody(BaseModel):
    alias: str
    dataset: str  # dataset name (resolved to DatasetRef with current revision)


class AssetCreate(BaseModel):
    name: str
    source: str
    bindings: list[BindingBody] = Field(default_factory=list)
    chart_type: Literal["bar", "line", "pie", "scatter", "histogram", "box", "heatmap", "area"]
    params: dict[str, Any] | None = None
    description: str = ""


class ParamsPut(BaseModel):
    params: dict[str, Any]
    expected_version: int | None = None


class PlacementPatch(BaseModel):
    placement: Placement


class RollbackBody(BaseModel):
    to_version: int
    expected_version: int | None = None


def _svc(request: Request):
    return request.app.state.canvas


def _err(status: int, msg: str) -> HTTPException:
    return HTTPException(status_code=status, detail=msg)


@router.post("", status_code=201)
def create_asset(body: AssetCreate, request: Request) -> dict[str, Any]:
    svc = _svc(request)
    problems = check_processor_source(body.source)
    if problems:
        raise _err(400, "; ".join(problems))
    spec_raw, defaults = extract_literals(body.source)
    try:
        spec = [ParamField(**p) for p in spec_raw]
    except Exception as e:  # pydantic ValidationError on malformed spec
        raise _err(400, f"PARAM_SPEC malformed: {e}") from e
    params = merge_defaults(spec, body.params or defaults)
    errs = validate_params(spec, params)
    if errs:
        raise _err(400, "; ".join(errs))
    bindings = []
    for b in body.bindings:
        try:
            ds = svc.repo.get_by_name(b.dataset)
        except DatasetNotFound:
            raise _err(400, f"dataset {b.dataset!r} not found") from None
        bindings.append(DataSourceBinding(alias=b.alias, dataset=ds.ref))
    asset = ChartAsset(name=body.name, bindings=bindings, param_spec=spec, params=params,
                       chart_type=body.chart_type, description=body.description)
    try:
        asset = svc.assets.create(asset, body.source)
    except DuplicateAssetName as e:
        raise _err(409, str(e)) from e
    result = svc.replay.replay(asset.id, trigger="create")
    return {"asset": svc.assets.get(asset.id).model_dump(), "gate": result.gate.model_dump()}


@router.get("")
def list_assets(request: Request) -> list[dict[str, Any]]:
    return [r.model_dump() for r in _svc(request).assets.list()]


@router.get("/{asset_id}")
def get_asset(asset_id: str, request: Request) -> dict[str, Any]:
    svc = _svc(request)
    try:
        asset = svc.assets.get(asset_id)
    except AssetNotFound:
        raise _err(404, "asset not found") from None
    return {"asset": asset.model_dump(), "source": svc.assets.load_source(asset_id)}


@router.get("/{asset_id}/render")
def get_render(asset_id: str, request: Request) -> dict[str, Any]:
    svc = _svc(request)
    try:
        asset = svc.assets.get(asset_id)
    except AssetNotFound:
        raise _err(404, "asset not found") from None
    pair = svc.assets.read_render(asset_id)
    if pair is None:
        raise _err(409, "no gate-passed render yet")
    return {"render": pair[0], "config": pair[1], "version": asset.version,
            "gate_passed": asset.last_gate.passed if asset.last_gate else None}


@router.post("/{asset_id}/replay")
def replay_asset(asset_id: str, request: Request) -> dict[str, Any]:
    svc = _svc(request)
    try:
        result = svc.replay.replay(asset_id, trigger="manual")
    except AssetNotFound:
        raise _err(404, "asset not found") from None
    return result.model_dump()


@router.put("/{asset_id}/params")
def put_params(asset_id: str, body: ParamsPut, request: Request) -> dict[str, Any]:
    svc = _svc(request)
    try:
        asset = svc.assets.get(asset_id)
    except AssetNotFound:
        raise _err(404, "asset not found") from None
    body.params = merge_defaults(asset.param_spec, body.params)
    errs = validate_params(asset.param_spec, body.params)
    if errs:
        raise _err(400, "; ".join(errs))
    try:
        if asset.version != body.expected_version and body.expected_version is not None:
            raise ConflictError(f"asset at v{asset.version}, expected v{body.expected_version}")
        params = merge_defaults(asset.param_spec, body.params)
        # write params.json through the asset service to keep content hash honest
        result = svc.assets.save_source(
            asset_id, svc.assets.load_source(asset_id), params,
            expected_version=body.expected_version,
        )
    except ConflictError as e:
        raise _err(409, str(e)) from e
    return {"asset": result.model_dump(), "needs_replay": True}


@router.patch("/{asset_id}/canvas")
def patch_canvas(asset_id: str, body: PlacementPatch, request: Request) -> dict[str, Any]:
    try:
        _svc(request).assets.set_placement(asset_id, body.placement)
    except AssetNotFound:
        raise _err(404, "asset not found") from None
    return {"ok": True}


@router.post("/{asset_id}/rollback")
def rollback(asset_id: str, body: RollbackBody, request: Request) -> dict[str, Any]:
    svc = _svc(request)
    try:
        result = svc.assets.rollback(asset_id, body.to_version,
                                      expected_version=body.expected_version)
    except AssetNotFound:
        raise _err(404, "asset or version not found") from None
    except ConflictError as e:
        raise _err(409, str(e)) from e
    gate = svc.replay.replay(result.id, trigger="rollback")
    return {"asset": result.model_dump(), "gate": gate.gate.model_dump()}


@router.get("/{asset_id}/history")
def history(asset_id: str, request: Request) -> dict[str, Any]:
    try:
        _svc(request).assets.get(asset_id)
        return _svc(request).assets.history(asset_id)
    except AssetNotFound:
        raise _err(404, "asset not found") from None


class PromoteBody(BaseModel):
    adhoc_id: str
    name: str | None = None


@router.post("/promote", status_code=201)
def promote_adhoc(body: PromoteBody, request: Request) -> dict[str, Any]:
    """Light->heavy: deterministic seed from the adhoc's producing code, then the
    AI rewrites it into a replay-legal processor before save (two approvals)."""
    from ..canvas.models import ProvenanceInfo
    from ..canvas.sourcecheck import extract_literals

    svc = _svc(request)
    adhoc = request.app.state.store.get_adhoc(body.adhoc_id)
    if adhoc is None:
        raise _err(404, "adhoc not found")
    source = adhoc["source_code"] or (
        "PARAM_SPEC = []\nDEFAULTS = {}\n\n\ndef process(ctx):\n    raise NotImplementedError\n"
    )
    spec_raw, defaults = extract_literals(source)
    try:
        spec = [ParamField(**p) for p in spec_raw]
    except Exception:  # noqa: BLE001 — bad seed spec just means AI re-declares it
        spec = []
    chart_type = str(((adhoc["payload"].get("config") or {}).get("chart_type")) or "bar")
    asset = ChartAsset(
        name=body.name or f"promoted_{adhoc['id'][:8]}",
        param_spec=spec,
        params=defaults,
        chart_type=chart_type,
        provenance=ProvenanceInfo(created_by="promote", adhoc_id=adhoc["id"],
                                  session_id=adhoc.get("session_id")),
    )
    asset = svc.assets.create(asset, source)
    seed = (f"资产 {asset.id} 已从即席图 {adhoc['id']} seed（provenance=promote）。"
            f"请把它改写为合规 processor：用 ctx.data 重读绑定数据、聚合后返回 "
            f"(RenderData, ChartConfig)，write_processor 修订 → validate_asset 过闸 → save_asset。")
    return {"asset_id": asset.id, "status": asset.status.value, "seed_message": seed}


@router.delete("/{asset_id}", status_code=204)
def delete_asset(asset_id: str, request: Request) -> None:
    try:
        _svc(request).assets.delete(asset_id)
    except AssetNotFound:
        raise _err(404, "asset not found") from None
