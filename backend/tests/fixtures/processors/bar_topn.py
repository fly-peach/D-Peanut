"""Seed processor: Top-N cities by revenue as a bar chart (N2 contract-lock fixture)."""

from data_agent.schemas.chart import ChartConfig, DataMap, RenderColumn, RenderData, RenderTable

PARAM_SPEC = [
    {"key": "top_n", "label": "城市数量", "type": "int", "default": 5, "min": 1, "max": 50,
     "affects": "data"},
]
DEFAULTS = {"top_n": 5}



def process(ctx):
    df = ctx.data["sales"]
    agg = (
        df.dropna(subset=["revenue"])
        .groupby("city", as_index=False)["revenue"]
        .sum()
        .sort_values(["revenue", "city"], ascending=[False, True], kind="stable")
        .head(int(ctx.params["top_n"]))
    )
    cities = [str(x) for x in agg["city"].tolist()]
    revs = [float(x) for x in agg["revenue"].tolist()]
    ctx.log(f"aggregated {len(cities)} cities")
    render = RenderData(tables={
        "main": RenderTable(dimensions=["city", "revenue"], source=[
            RenderColumn(name="city", dtype="str", values=cities),
            RenderColumn(name="revenue", dtype="float", values=revs),
        ])
    }).with_defaults()
    config = ChartConfig(chart_type="bar", title=f"Top {len(cities)} 城市销售额",
                         data_map=DataMap(map={"x": "main.city", "y": "main.revenue"}))
    return render, config
