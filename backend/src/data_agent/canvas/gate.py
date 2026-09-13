"""Output schema gate — pure function, table-driven tests (design decision 5).

Order (short-circuit, all cheap): columns (SUBSET semantics — extras tolerated) ->
dtype family -> row_bounds -> payload_limit. dtype families: int~float
interchangeable (numeric); date~datetime interchangeable; str strict.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime

from ..schemas.chart import RenderData
from .models import GateCheck, GateReport, OutputField, OutputSchema, OutputTable

PAYLOAD_LIMIT_BYTES = 2 * 1024 * 1024
_NUMERIC = {"int", "float"}
_TEMPORAL = {"date", "datetime"}

DEFAULT_MAX_ROWS = 100_000


def _family(dtype: str) -> set[str]:
    d = (dtype or "").lower()
    if d in _NUMERIC or d.startswith(("int", "uint", "float")):
        return _NUMERIC
    if d in _TEMPORAL or "datetime" in d or d == "date" or d.startswith("timestamp"):
        return _TEMPORAL
    if d == "bool":
        return {"bool"}
    return {"str"}


def dtype_compatible(expected: str, actual: str) -> bool:
    return expected in _family(actual)


def stamp_schema(render: RenderData, max_rows: int = DEFAULT_MAX_ROWS) -> OutputSchema:
    """Draft first-gate: derive the schema from the actual passing output."""
    tables = []
    for name, table in render.tables.items():
        cols = [
            OutputField(name=c.name, dtype=min(_family(c.dtype)))  # family representative
            for c in table.source
        ]
        rows = len(table.source[0].values) if table.source else 0
        tables.append(OutputTable(name=name, columns=cols, min_rows=0,
                                  max_rows=max(max_rows, rows)))
    return OutputSchema(tables=tables)


def validate_output(
    asset_id: str,
    version: int,
    render: RenderData | None,
    schema: OutputSchema | None,
    *,
    exec_error: str | None = None,
    timed_out: bool = False,
    elapsed_s: float = 0.0,
) -> GateReport:
    checks: list[GateCheck] = []
    errors: list[str] = []

    def fail(kind: str, expected: str, actual: str, msg: str) -> GateReport:
        checks.append(GateCheck(kind=kind, expected=expected, actual=actual, passed=False))
        errors.append(msg)
        return _report(asset_id, version, checks, errors, elapsed_s)

    if timed_out:
        return fail("timeout", "<=30s", f">{elapsed_s:.0f}s",
                    "replay timed out (30s); reduce work or aggregate before rendering")
    if exec_error:
        return fail("exec", "processor runs clean", exec_error[:300],
                    f"processor raised an error: {exec_error[:300]}")
    if render is None:
        return fail("exec", "a result payload", "none",
                    "process() returned no (RenderData, ChartConfig) pair")
    if schema is None:
        # draft first-gate: no schema yet — this output WILL be the stamp
        checks.append(GateCheck(kind="columns", expected="first-gate stamp",
                                actual="pending", passed=True))
        return _report(asset_id, version, checks, errors, elapsed_s)

    schema_tables = {t.name: t for t in schema.tables}
    render_tables = render.tables
    if set(schema_tables) != set(render_tables):
        return fail("columns", str(sorted(schema_tables)), str(sorted(render_tables)),
                    "table set drifted: expected "
                    f"{sorted(schema_tables)}, got {sorted(render_tables)}")
    for name, want in schema_tables.items():
        got = render_tables[name]
        want_cols = {c.name for c in want.columns}
        got_cols = {c.name for c in got.source}
        missing = sorted(want_cols - got_cols)
        if missing:  # subset semantics: extras tolerated, missing = fail
            return fail("columns", str(sorted(want_cols)), str(sorted(got_cols)),
                        f"table {name!r}: missing columns {missing} (extras tolerated)")
        wmap = {c.name: c.dtype for c in want.columns}
        for c in got.source:
            if c.name in wmap and not dtype_compatible(wmap[c.name], c.dtype):
                return fail("dtypes", f"{c.name}:{wmap[c.name]}", f"{c.name}:{c.dtype}",
                            f"column {name!r}.{c.name} dtype family changed: "
                            f"expected {wmap[c.name]}*, got {c.dtype}")
    for name, want in schema_tables.items():
        got = render_tables[name]
        n = len(got.source[0].values) if got.source else 0
        if not (want.min_rows <= n <= want.max_rows):
            return fail("row_bounds", f"{want.min_rows}..{want.max_rows}", str(n),
                        f"table {name!r} returned {n} rows outside "
                        f"[{want.min_rows}, {want.max_rows}] — add LIMIT/TopN")
    payload = len(render.model_dump_json().encode("utf-8"))
    if payload > PAYLOAD_LIMIT_BYTES:
        return fail("payload", f"<={PAYLOAD_LIMIT_BYTES}", str(payload),
                    f"payload {payload / 1e6:.1f}MB exceeds 2MB — aggregate before rendering")
    checks.append(GateCheck(kind="payload", expected=f"<={PAYLOAD_LIMIT_BYTES}",
                            actual=str(payload), passed=True))
    return _report(asset_id, version, checks, errors, elapsed_s)


def _report(asset_id: str, version: int, checks: list[GateCheck], errors: list[str],
            elapsed: float) -> GateReport:
    return GateReport(
        asset_id=asset_id, version=version, passed=not errors, checks=checks, errors=errors,
        elapsed_s=round(elapsed, 3), ran_at=datetime.now(UTC).isoformat(),
    )


def json_size(obj: object) -> int:
    return len(json.dumps(obj, ensure_ascii=False).encode("utf-8"))
