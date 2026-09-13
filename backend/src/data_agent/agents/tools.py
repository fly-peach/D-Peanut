"""The ten coding-agent tools (agent-design v3 §3; signatures frozen at N3 end).

All ten are thin shells over the SAME services the REST plane uses:
catalog pipeline/repo (browse/inspect/query/kernel data), canvas assets/replay
(write/validate/patch/save), session kernel (run_in_kernel). Approval gating:
write_processor & save_asset carry requires_approval; run_in_kernel / query_data
raise ApprovalRequired when the AST verifier flags blocked patterns.
"""

from __future__ import annotations

import re
from typing import Any

import duckdb
from pydantic_ai import Agent, ApprovalRequired, RunContext, ToolReturn

from ..canvas.models import AssetStatus, ChartAsset, DataSourceBinding, ParamField
from ..canvas.params import merge_defaults, validate_params
from ..canvas.sourcecheck import check_processor_source, extract_literals
from ..catalog.registry import NotFoundError
from ..catalog.sampler import effective_privacy
from ..exec.kernel_pool import KernelPool
from ..exec.verifier import verify_code
from ..runs.budget import BudgetExceeded
from .deps import AgentDeps

_WRITE_SQL = re.compile(
    r"\b(insert|update|delete|drop|create|alter|attach|detach|copy|export|install|load|vacuum)\b",
    re.I,
)

def _track(ctx: RunContext[AgentDeps]) -> None:
    """Mirror live usage into run state (budget sniffing + data-run summary)."""
    usage = ctx.usage
    st = ctx.deps.state
    st.usage_tokens = int(getattr(usage, "total_tokens", 0) or 0)
    st.usage_cost = float(getattr(usage, "cost_usd", None) or 0.0)
    budget = ctx.deps.settings
    if st.usage_tokens > budget.budget_tokens or st.usage_cost > budget.budget_usd:
        raise BudgetExceeded("tokens" if st.usage_tokens > budget.budget_tokens else "usd",
                             st.usage_tokens if st.usage_tokens else st.usage_cost,
                             budget.budget_tokens if st.usage_tokens > budget.budget_tokens
                             else budget.budget_usd)


# --- registration entry point -------------------------------------------------


def register_all(agent: Agent[AgentDeps, Any]) -> None:
    agent.tool(browse_datasource)
    agent.tool(inspect_profile)
    agent.tool(query_data)
    agent.tool(run_in_kernel)
    agent.tool(read_asset)
    agent.tool(write_processor, requires_approval=True)
    agent.tool(validate_asset)
    agent.tool(patch_params)
    agent.tool(save_asset, requires_approval=True)
    agent.tool(emit_adhoc_chart)


# --- catalog / exploration -------------------------------------------------------


def browse_datasource(ctx: RunContext[AgentDeps], name_prefix: str | None = None,
                      kind: str | None = None) -> list[dict[str, Any]]:
    """Browse the dataset directory: id/name/kind/revision/row_count/status."""
    briefs = ctx.deps.repo.list()
    out = []
    for b in briefs:
        if name_prefix and not b.name.startswith(name_prefix):
            continue
        if kind and b.kind.value != kind:
            continue
        out.append(b.model_dump(include={"id", "name", "kind", "revision",
                                         "scan_status", "profile_status", "row_count",
                                         "privacy_mode"}))
    return out


def inspect_profile(ctx: RunContext[AgentDeps], dataset: str,
                    columns: list[str] | None = None,
                    sample_rows: int = 0) -> dict[str, Any]:
    """Column profile (+ optional sample rows; privacy degrades to stats only)."""
    deps = ctx.deps
    try:
        ds = deps.repo.get_by_name(dataset)
    except NotFoundError:
        return {"error": f"dataset {dataset!r} not found — browse_datasource first"}
    profile = deps.repo.get_profile(ds.id, ds.revision)
    if profile is None:
        return {"error": f"profile not ready for {dataset!r} (status={ds.profile_status.value})"}
    cols = profile.columns
    if columns:
        cols = [c for c in cols if c.name in columns]
    result: dict[str, Any] = {"dataset": ds.name, "revision": ds.revision,
                              "row_count": profile.row_count,
                              "columns": [c.model_dump() for c in cols]}
    if sample_rows > 0 and not effective_privacy(ds, deps.settings):
        from ..catalog import reader

        kwargs = {}
        if ds.kind == "sql":
            kwargs["conn_target"] = deps.canvas_replay.secrets.get(ds.meta.conn_ref)
        df = reader.read_dataset(ds, limit=min(sample_rows, 20), **kwargs)
        result["rows"] = df.head(min(sample_rows, 20)).to_dict("records")
    return result


def query_data(ctx: RunContext[AgentDeps], dataset: str, sql: str,
               limit: int = 200) -> dict[str, Any]:
    """DuckDB read-only SQL over one dataset (table name = the dataset's leaf name).

    Write/DDL statements are refused -> approval flow."""
    deps = ctx.deps
    if _WRITE_SQL.search(sql):
        raise ApprovalRequired("query_data 命中写/DDL 模式，需人工批准")
    try:
        ds = deps.repo.get_by_name(dataset)
    except NotFoundError:
        return {"error": f"dataset {dataset!r} not found"}
    from ..catalog import reader

    con = duckdb.connect()
    try:
        tbl = dataset.rsplit("/", 1)[-1].rsplit(".", 1)[0]
        tbl = re.sub(r"\W", "_", tbl) or "t"
        if ds.kind == "file" and ds.meta.format in ("csv", "parquet"):
            fn = "read_csv" if ds.meta.format == "csv" else "read_parquet"
            con.execute(f'CREATE TEMP VIEW "{tbl}" AS SELECT * FROM {fn}(?)', [ds.meta.path])
        else:
            kwargs = {"conn_target": deps.canvas_replay.secrets.get(ds.meta.conn_ref)} \
                if ds.kind == "sql" else {}
            df = reader.read_dataset(ds, **kwargs)
            con.register(tbl, df)
        limited = sql.rstrip().rstrip(";")
        if not re.search(r"\blimit\b", limited, re.I):
            limited += f" LIMIT {min(int(limit), 1000)}"
        df = con.execute(limited).fetch_df()
        truncated = len(df) >= min(int(limit), 1000)
        return {"columns": list(df.columns), "rows": df.head(100).to_dict("records"),
                "row_count": len(df), "truncated": truncated, "table": tbl}
    except Exception as e:  # noqa: BLE001 — errors are the model's reading material
        return {"error": f"{type(e).__name__}: {str(e)[:400]}"}
    finally:
        con.close()


# --- session kernel -----------------------------------------------------------

_LAST_KERNEL: dict[str, str] = {}  # session_id -> code_ref of last run_in_kernel (adhoc link)


def run_in_kernel(
    ctx: RunContext[AgentDeps], code: str, purpose: str
) -> ToolReturn[dict[str, Any]]:
    """Trial-run python in the SESSION kernel (variables persist across calls).

    Blocked patterns (net/disk write/DDL/eval...) raise ApprovalRequired BEFORE
    execution. Execution failures feed the traceback back (reflect budget <= 3)."""
    deps = ctx.deps
    _track(ctx)
    verdict = verify_code(code)
    if not verdict.safe:
        raise ApprovalRequired(f"run_in_kernel 危险模式: {verdict.reason}")
    st = deps.state
    if st.reflects >= 3:
        return ToolReturn(
            {"ok": False,
             "error": "reflect 上限(3)已用尽：不要再重试执行，向用户如实说明已尝试什么、"
                      "失败原因与可选方向。",
             "reflects_remaining": 0},
            metadata={"kind": "exec", "code_ref": None},
        )
    pool: KernelPool = deps.kernel
    try:
        pool.start(session_id=st.session_id)  # idempotent guard below
    except ValueError:
        pass  # already running
    res = pool.execute(st.session_id, code, timeout_s=deps.settings.kernel_timeout_s)
    ref = st.cache_code(code, res.stdout[:2000])
    _LAST_KERNEL[st.session_id] = ref
    digest = (res.stdout[-2000:] if res.ok else (res.error or "")[-2000:])
    if not res.ok:
        st.reflects += 1
        st.last_error_summary = f"run_in_kernel({purpose}) 失败: {digest[:200]}"
    deps.store.add_step(st.run_id, len(st.asset_events) + st.reflects, "run_in_kernel",
                        "ok" if res.ok else "error", {"purpose": purpose}, digest[:400])
    return ToolReturn(
        {"ok": res.ok, "stdout": digest, "elapsed_s": round(res.elapsed_s, 3),
         "reflects_used": st.reflects, "reflects_left": max(0, 3 - st.reflects)},
        metadata={"kind": "exec", "code_ref": ref, "purpose": purpose},
    )


# --- asset authoring (canvas services underneath) ------------------------------


def read_asset(ctx: RunContext[AgentDeps], asset_id: str) -> dict[str, Any]:
    """Read the full current asset: source, params, param_spec, schema, last gate."""
    deps = ctx.deps
    try:
        asset = deps.canvas_assets.get(asset_id)
    except Exception:
        return {"error": f"asset {asset_id!r} not found"}
    return {"asset": asset.model_dump(),
            "source": deps.canvas_assets.load_source(asset_id),
            "drift": asset.status is AssetStatus.broken}


def write_processor(ctx: RunContext[AgentDeps], source: str,
                    bindings: list[dict[str, str]], name: str | None = None,
                    asset_id: str | None = None,
                    params: dict[str, Any] | None = None,
                    chart_type: str = "bar") -> dict[str, Any]:
    """Create or rewrite a draft asset's processor (+ immediate validation)."""
    deps = ctx.deps
    _track(ctx)
    problems = check_processor_source(source)
    if problems:
        return {"error": "源码不合三导出契约: " + "; ".join(problems)}
    spec_raw, defaults = extract_literals(source)
    try:
        spec = [ParamField(**p) for p in spec_raw]
    except Exception as e:  # noqa: BLE001
        return {"error": f"PARAM_SPEC 不合法: {e}"}
    merged = merge_defaults(spec, params or defaults)
    errs = validate_params(spec, merged)
    if errs:
        return {"error": "params 与 PARAM_SPEC 不一致: " + "; ".join(errs)}
    bnds: list[DataSourceBinding] = []
    for b in bindings:
        try:
            ds = deps.repo.get_by_name(b["dataset"])
        except (NotFoundError, KeyError):
            return {"error": f"绑定 dataset {b.get('dataset')!r} 不存在（先 browse_datasource）"}
        bnds.append(DataSourceBinding(alias=b["alias"], dataset=ds.ref))
    if asset_id:
        try:
            deps.canvas_assets.get(asset_id)
        except Exception:
            return {"error": f"asset {asset_id!r} not found"}
        asset = deps.canvas_assets.save_source(asset_id, source, params=merged)
    else:
        asset = deps.canvas_assets.create(
            ChartAsset(name=name or f"asset_{deps.state.run_id[:6]}_{len(deps.state.asset_events)}",
                       bindings=bnds, param_spec=spec, params=merged, chart_type=chart_type),
            source)
    result = deps.canvas_replay.replay(asset.id, trigger="validate")
    deps.state.asset_events.append({"asset_id": asset.id, "version": asset.version,
                                    "gate_passed": result.gate.passed, "trigger": "ai"})
    return {"asset_id": asset.id, "version": asset.version, "status": asset.status.value,
            "gate": {"passed": result.gate.passed, "errors": result.gate.errors,
                     "stamped": asset.output_schema is not None}}


def validate_asset(ctx: RunContext[AgentDeps], asset_id: str) -> dict[str, Any]:
    """Replay the asset in the clean kernel against the schema gate (no approval —
    this is your compiler; read errors structurally and fix)."""
    deps = ctx.deps
    _track(ctx)
    try:
        result = deps.canvas_replay.replay(asset_id, trigger="validate")
    except Exception:
        return {"error": f"asset {asset_id!r} not found"}
    deps.state.asset_events.append({"asset_id": asset_id, "version": result.version,
                                    "gate_passed": result.gate.passed, "trigger": "ai"})
    return {"passed": result.gate.passed, "errors": result.gate.errors,
            "version": result.version, "notes": result.notes[:5]}


def patch_params(ctx: RunContext[AgentDeps], asset_id: str,
                 params: dict[str, Any]) -> dict[str, Any]:
    """Update params only (validated against PARAM_SPEC; bad keys -> immediate error)."""
    deps = ctx.deps
    try:
        asset = deps.canvas_assets.get(asset_id)
    except Exception:
        return {"error": f"asset {asset_id!r} not found"}
    errs = validate_params(asset.param_spec, merge_defaults(asset.param_spec, params))
    if errs:
        return {"error": "; ".join(errs)}
    updated = deps.canvas_assets.write_params(asset, merge_defaults(asset.param_spec, params))
    return {"asset_id": updated.id, "version": updated.version, "status": updated.status.value,
            "hint": "data 参数改后需 validate_asset 过闸才可 save"}


def save_asset(ctx: RunContext[AgentDeps], asset_id: str,
               canvas: dict[str, int] | None = None) -> dict[str, Any]:
    """Promote a VALIDATED asset onto the canvas (the only write-to-canvas gate)."""
    deps = ctx.deps
    _track(ctx)
    try:
        asset = deps.canvas_assets.get(asset_id)
    except Exception:
        return {"error": f"asset {asset_id!r} not found"}
    if asset.status not in (AssetStatus.validated,):
        return {"error": f"status={asset.status.value}，必须先 validate_asset 过闸（禁止绕过闸门）"}
    from ..canvas.models import Placement

    if canvas:
        asset.placement = Placement(**{**asset.placement.model_dump(), **canvas})
    asset.status = AssetStatus.on_canvas
    deps.canvas_assets.update(asset)
    deps.state.asset_events.append({"asset_id": asset.id, "version": asset.version,
                                    "gate_passed": True, "trigger": "ai"})
    return {"asset_id": asset.id, "version": asset.version, "status": "on_canvas",
            "name": asset.name}


# --- light mode (adhoc) ---------------------------------------------------------


def emit_adhoc_chart(ctx: RunContext[AgentDeps], title: str, render: dict[str, Any],
                     config: dict[str, Any], code_ref: str) -> ToolReturn[str]:
    """Emit a one-off chart card into the conversation (no asset, no persistence
    on canvas). code_ref = the run_in_kernel call that produced it (promote seed)."""
    deps = ctx.deps
    cached = deps.state.code_cache.get(code_ref)
    source = cached["code"] if cached else ""
    payload = {"title": title, "render": render, "config": config, "code_ref": code_ref}
    aid = deps.store.save_adhoc(deps.state.session_id, deps.state.run_id, payload, source)
    return ToolReturn(f"已出一次性图：{title}",
                      metadata={"kind": "adhoc", "adhoc_id": aid, "payload": payload})
