"""System instructions (agent-design v3 §2): static seven blocks + processor
template + per-run dynamic context. The dynamic part is a pure function so token
budgets / privacy can be asserted without a model call."""

from __future__ import annotations

from typing import TYPE_CHECKING

from ..catalog.profiler import render_profile_for_prompt

if TYPE_CHECKING:
    from .deps import AgentDeps

STATIC_INSTRUCTIONS = """\
你在为数据画布编写可重放的 processor。你有一个会话常驻试跑内核（变量跨轮、数据集按名
懒注入）；但资产上线跑在 clean 内核——重放内核不认任何会话变量。pandas/duckdb 预装。

【数据事实优先】只依据 inspect_profile / query_data / 执行输出说话；禁止虚构列名和数值；
不确定先查再写。

【编写纪律】先 run_in_kernel 试跑看到真实结果，才准 write_processor；processor 必须导出
PARAM_SPEC / DEFAULTS / process(ctx) 三件套（模板如下），process 是纯函数——只从 ctx 取数，
只返回 (RenderData, ChartConfig)；写完必 validate_asset 过闸，读结构化 errors 修正再闸，
最多 3 次；save 前必须 status=validated。

【轻/重模式】用户只想看一眼 → 试跑后 emit_adhoc_chart（一次性卡，别建资产）；要常驻、要
改参、要跟数据刷新 → 走资产环。不确定时问一句。promote 请求 = 把 adhoc 的 code_ref 改写
为 ctx 重读绑定数据的合规 processor，不是照抄。

【渲染契约】ChartConfig.option_template 纯 JSON（禁函数字符串）；类型白名单
bar/line/pie/scatter/histogram/box/heatmap/area；数据寻址走 data_map "table.column"；
外观（高宽字体图例色板）放 appearance；PARAM_SPEC 是用户表单唯一来源——每个可调参数都要
声明 key/label/type/default/范围/affects(data|appearance)，docstring 写明参数语义。
先聚合再渲染：RenderData 有 2MB/行数闸门，明细大表不许直塞。

【失败协议】traceback / GateReport 如实读，修正重试上限 3；仍失败说明已尝试什么与可选
方向；禁止静默吞错、禁止绕过闸门（例如把聚合失败改成硬编码样例数据）。

【安全与在场】run_in_kernel/query_data 命中危险模式（网络/写盘/DDL/删改/eval）会被 AST
分级拦截转人工审批——被拒后给替代方案，不重试同一路径。AI toggle 关闭时你不接单。隐私
模式（schema-only）下回答与产物不含原始行数据。与用户同语言（默认中文），代码注释英文。

PROCESSOR 模板:
```python
PARAM_SPEC = [{"key": "top_n", "label": "数量", "type": "int", "default": 5,
               "min": 1, "max": 50, "affects": "data"}]
DEFAULTS = {"top_n": 5}

from data_agent.schemas.chart import (Appearance, ChartConfig, DataMap,
                                      RenderColumn, RenderData, RenderTable)

def process(ctx):
    # ctx.params: dict; ctx.data["<alias>"]: DataFrame(懒加载,只读); ctx.log(msg): 调试
    df = ctx.data["<alias>"]
    agg = df.groupby("city", as_index=False)["revenue"].sum() \
            .sort_values("revenue", ascending=False).head(int(ctx.params["top_n"]))
    render = RenderData(tables={"main": RenderTable(
        dimensions=["city", "revenue"],
        source=[RenderColumn(name="city", dtype="str", values=[str(x) for x in agg["city"]]),
                RenderColumn(name="revenue", dtype="float",
                             values=[float(x) for x in agg["revenue"]])])}).with_defaults()
    config = ChartConfig(chart_type="bar", title="Top 城市",
                         data_map=DataMap(map={"x": "main.city", "y": "main.revenue"}),
                         appearance=Appearance(height=320))
    return render, config
```
"""


def render_dynamic_prompt(deps: AgentDeps, kernel_vars: list[str]) -> str:
    """Per-run injected context: dataset catalog (+request-time profiles omitted here —
    the agent pulls via inspect_profile), trial-kernel variable state, toggles, last
    failure summary."""
    lines: list[str] = ["--- 当前会话上下文 ---"]
    briefs = deps.repo.list()
    files = [b for b in briefs if b.kind != "folder"]
    if files:
        lines.append("数据集(按名引用；alias 用 name)：")
        for b in files[:40]:
            lines.append(f"- {b.name} [{b.kind} rev={b.revision[:12]} "
                         f"rows={b.row_count if b.row_count is not None else '?'} "
                         f"profile={b.profile_status}"
                         + (", 🔒schema-only" if (b.privacy_mode or deps.settings.privacy_default)
                           else "")
                         + "]")
        if len(files) > 40:
            lines.append(f"- …另有 {len(files) - 40} 个，browse_datasource 查询")
    else:
        lines.append("暂无数据集——建议用户先到数据源页注册。")
    if kernel_vars:
        lines.append("试跑内核现存变量(仅探索用，资产禁止依赖): " + ", ".join(kernel_vars[:30]))
    else:
        lines.append("试跑内核无用户变量。")
    if not deps.ai_enabled:
        lines.append("AI toggle 当前为 OFF：你不会收到请求。")
    if deps.run_state.last_error_summary:
        lines.append("上次失败摘要(避免重复踩坑): " + deps.run_state.last_error_summary[:400])
    lines.append(f"语言: {deps.settings.language} | 时区: {deps.settings.timezone}")
    return "\n".join(lines)


def profile_hint(profiles_text: str) -> str:
    return "--- 相关画像(预算内) ---\n" + profiles_text


def budgeted_profiles(deps: AgentDeps, dataset_names: list[str],
                      budget_tokens: int = 500) -> str:
    """Render cached profiles for prompt, per-table budget enforced (pure path)."""
    from ..catalog.registry import NotFoundError

    out = []
    for name in dataset_names:
        try:
            ds = deps.repo.get_by_name(name)
        except NotFoundError:
            continue
        prof = deps.repo.get_profile(ds.id, ds.revision)
        if prof is None:
            continue
        out.append(render_profile_for_prompt(prof, budget_tokens=budget_tokens))
    return "\n".join(out)
