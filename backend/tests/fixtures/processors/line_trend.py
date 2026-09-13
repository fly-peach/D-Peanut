"""Seed processor: monthly revenue trend as a line chart."""

from data_agent.schemas.chart import ChartConfig, DataMap, RenderColumn, RenderData, RenderTable

PARAM_SPEC = [
    {"key": "metric", "label": "指标", "type": "select", "default": "revenue",
     "options": ["revenue", "units"], "affects": "data"},
]
DEFAULTS = {"metric": "revenue"}



def process(ctx):
    df = ctx.data["sales"]
    metric = str(ctx.params["metric"])
    agg = df.groupby("month", as_index=False)[metric].sum().sort_values("month", kind="stable")
    months = [str(x) for x in agg["month"].tolist()]
    vals = [float(x) for x in agg[metric].tolist()]
    render = RenderData(tables={
        "main": RenderTable(dimensions=["month", metric], source=[
            RenderColumn(name="month", dtype="str", values=months),
            RenderColumn(name=metric, dtype="float", values=vals),
        ])
    }).with_defaults()
    config = ChartConfig(chart_type="line", title=f"月度{metric}趋势",
                         data_map=DataMap(map={"x": "main.month", "y": f"main.{metric}"}))
    return render, config
