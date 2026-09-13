/** Seed processor sources for creating demo cards before N3 (mirror of
 * backend/tests/fixtures/processors/bar_topn.py — kept byte-identical to the
 * contract-lock fixture so UI demo and CI test exercise the same processor). */

export const BAR_TOPN_SOURCE = `"""Seed processor: Top-N cities by revenue as a bar chart (N2 contract-lock fixture)."""

from data_agent.schemas.chart import (
    Appearance,
    ChartConfig,
    DataMap,
    RenderColumn,
    RenderData,
    RenderTable,
)

PARAM_SPEC = [
    {"key": "top_n", "label": "城市数量", "type": "int", "default": 5, "min": 1, "max": 50,
     "affects": "data"},
    {"key": "height", "label": "图表高度 px", "type": "int", "default": 320, "min": 120,
     "max": 800, "affects": "appearance"},
    {"key": "show_label", "label": "显示数值标签", "type": "bool", "default": False,
     "affects": "appearance"},
]
DEFAULTS = {"top_n": 5, "height": 320, "show_label": False}


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
    config = ChartConfig(
        chart_type="bar", title=f"Top {len(cities)} 城市销售额",
        data_map=DataMap(map={"x": "main.city", "y": "main.revenue"}),
        appearance=Appearance(height=int(ctx.params.get("height", 320)),
                              show_label=bool(ctx.params.get("show_label", False))),
    )
    return render, config
`
