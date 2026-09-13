"""Gate pure-function table-driven tests (N2 task 1.3)."""


from data_agent.canvas.gate import stamp_schema, validate_output
from data_agent.canvas.models import OutputField, OutputSchema, OutputTable
from data_agent.schemas.chart import RenderColumn, RenderData, RenderTable

RENDER = RenderData(tables={
    "main": RenderTable(dimensions=["city", "revenue"], source=[
        RenderColumn(name="city", dtype="str", values=["A", "B"]),
        RenderColumn(name="revenue", dtype="float", values=[1.5, 2.5]),
    ])
}).with_defaults()

SCHEMA = OutputSchema(tables=[OutputTable(
    name="main",
    columns=[OutputField(name="city", dtype="str"), OutputField(name="revenue", dtype="float")],
    min_rows=0, max_rows=100,
)])


def _gate(render=RENDER, schema=SCHEMA, **kw):
    return validate_output("ca_x", 1, render, schema, **kw)


class TestPassPaths:
    def test_clean_pass(self):
        r = _gate()
        assert r.passed and not r.errors

    def test_int_float_interchangeable(self):
        r = _gate(render=RenderData(tables={
            "main": RenderTable(dimensions=["city", "revenue"], source=[
                RenderColumn(name="city", dtype="str", values=["A"]),
                RenderColumn(name="revenue", dtype="int", values=[3]),
            ])
        }).with_defaults())
        assert r.passed

    def test_extra_column_tolerated(self):
        r = _gate(render=RenderData(tables={
            "main": RenderTable(dimensions=["city", "revenue", "share"], source=[
                RenderColumn(name="city", dtype="str", values=["A"]),
                RenderColumn(name="revenue", dtype="float", values=[1.5]),
                RenderColumn(name="share", dtype="float", values=[0.1]),
            ])
        }).with_defaults())
        assert r.passed

    def test_draft_stamp_pending_passes(self):
        r = _gate(schema=None)
        assert r.passed


class TestFailPaths:
    def test_missing_column(self):
        r = _gate(render=RenderData(tables={
            "main": RenderTable(dimensions=["city"], source=[
                RenderColumn(name="city", dtype="str", values=["A"]),
            ])
        }).with_defaults())
        assert not r.passed and "missing columns" in r.errors[0] and "'revenue'" in r.errors[0]

    def test_table_set_drift(self):
        r = _gate(render=RenderData(tables={
            "other": RenderTable(dimensions=["city"], source=[
                RenderColumn(name="city", dtype="str", values=["A"])])
        }).with_defaults())
        assert not r.passed and "table set" in r.errors[0]

    def test_dtype_family_break(self):
        r = _gate(render=RenderData(tables={
            "main": RenderTable(dimensions=["city", "revenue"], source=[
                RenderColumn(name="city", dtype="str", values=["A"]),
                RenderColumn(name="revenue", dtype="str", values=["x"]),
            ])
        }).with_defaults())
        assert not r.passed and "dtype family" in r.errors[0]

    def test_row_bounds(self):
        schema = OutputSchema(tables=[OutputTable(
            name="main",
            columns=[OutputField(name="city", dtype="str"),
                     OutputField(name="revenue", dtype="float")],
            min_rows=5, max_rows=100)])
        assert not _gate(schema=schema).passed

    def test_payload_limit(self):
        big = ["x" * 200] * 20_000
        schema = OutputSchema(tables=[OutputTable(
            name="main",
            columns=[OutputField(name="city", dtype="str"),
                     OutputField(name="revenue", dtype="float")],
            min_rows=0, max_rows=25_000)])
        r = _gate(schema=schema, render=RenderData(tables={
            "main": RenderTable(dimensions=["city", "revenue"], source=[
                RenderColumn(name="city", dtype="str", values=big),
                RenderColumn(name="revenue", dtype="float", values=[1.0] * 20_000),
            ])
        }).with_defaults())
        assert not r.passed and "payload" in r.errors[0].lower()

    def test_exec_error_and_timeout_short_circuit(self):
        assert not _gate(exec_error="KeyError: revenue").passed
        rt = _gate(timed_out=True, elapsed_s=31)
        assert not rt.passed and "timed out" in rt.errors[0]

    def test_missing_result_pair(self):
        r = _gate(render=None)
        assert not r.passed and "RenderData" in r.errors[0]


class TestStamp:
    def test_stamp_roundtrip(self):
        stamped = stamp_schema(RENDER)
        assert _gate(schema=stamped).passed
        assert stamped.tables[0].max_rows >= 2
