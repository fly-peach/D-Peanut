"""Seed processor: channel × city revenue matrix as a heatmap."""

from data_agent.schemas.chart import ChartConfig, DataMap, RenderColumn, RenderData, RenderTable

PARAM_SPEC = [
    {"key": "per_unit", "label": "按客单价(均值)而非总额", "type": "bool", "default": False,
     "affects": "data"},
]
DEFAULTS = {"per_unit": False}



def process(ctx):
    df = ctx.data["sales"].dropna(subset=["revenue"])
    if bool(ctx.params["per_unit"]):
        g = df.groupby(["channel", "city"], as_index=False)["revenue"].mean()
        col = "avg_revenue"
        g = g.rename(columns={"revenue": col})
    else:
        g = df.groupby(["channel", "city"], as_index=False)["revenue"].sum()
        col = "total_revenue"
    g = g.sort_values(["channel", "city"], kind="stable")
    render = RenderData(tables={
        "main": RenderTable(dimensions=["channel", "city", col], source=[
            RenderColumn(name="channel", dtype="str", values=[str(x) for x in g["channel"]]),
            RenderColumn(name="city", dtype="str", values=[str(x) for x in g["city"]]),
            RenderColumn(name=col, dtype="float", values=[float(x) for x in g[col]]),
        ])
    }).with_defaults()
    config = ChartConfig(chart_type="heatmap", title="渠道×城市营收",
                         data_map=DataMap(map={"x": "main.city", "y": "main.channel",
                                               "v": f"main.{col}"}))
    return render, config
