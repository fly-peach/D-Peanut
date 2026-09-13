"""Profiler field correctness + prompt budget trimming (tasks 2.4)."""

import pandas as pd

from data_agent.catalog.profiler import (
    est_tokens,
    profile_dataframe,
    render_profile_for_prompt,
)

FIX = pd.DataFrame(
    {
        "id": list(range(10)),
        "revenue": [1.5 * i if i % 4 else float("nan") for i in range(10)],
        "month": ["2021-01-05", "2021-02-03", "2021-03-11", "2021-04-02"] * 2
        + ["2021-05-01", "2021-05-02"],
        "city": ["上海", "北京", "广州", "深圳"] * 2 + ["杭州"] * 2,
        "flag": [True, False] * 5,
    }
)


def make_profile(df=FIX):
    return profile_dataframe(df, "ds_test", "rev1", row_count=len(df))


class TestColumnStats:
    def test_numeric_and_null(self):
        col = {c.name: c for c in make_profile().columns}["revenue"]
        assert 0 < col.null_rate < 0.4
        assert col.num_range and col.num_range[0] >= 0
        assert col.cardinality == col.cardinality  # present
        assert not col.is_time

    def test_time_column_detected_from_strings(self):
        col = {c.name: c for c in make_profile().columns}["month"]
        assert col.is_time
        assert col.time_min.startswith("2021-01") and col.time_max.startswith("2021-05")

    def test_category_top_values_and_samples(self):
        col = {c.name: c for c in make_profile().columns}["city"]
        assert col.top_values and col.top_values[0] == "上海"
        assert col.sample_values[:1] == ["上海"]

    def test_pk_hint_on_unique_non_null(self):
        col = {c.name: c for c in make_profile().columns}["id"]
        assert col.pk_hint
        assert not {c.name: c for c in make_profile().columns}["revenue"].pk_hint

    def test_bool_not_numeric_range(self):
        col = {c.name: c for c in make_profile().columns}["flag"]
        assert col.num_range is None


class TestPromptRender:
    def test_small_profile_fits_and_includes_detail(self):
        text = render_profile_for_prompt(make_profile(), budget_tokens=500)
        assert "revenue" in text and "samples" in text
        assert est_tokens(text) <= 500

    def test_budget_trim_order(self):
        wide = pd.DataFrame({f"c{i}": ["value-a", "value-b"] * 3 for i in range(60)})
        prof = make_profile(wide)
        full = render_profile_for_prompt(prof, budget_tokens=10_000)
        assert "samples" in full
        trimmed = render_profile_for_prompt(prof, budget_tokens=500)
        assert est_tokens(trimmed) <= 500
        assert "samples" not in trimmed  # sample_values dropped first
        assert "c0" in trimmed  # names survive to the last tier

    def test_privacy_strips_raw_values(self):
        text = render_profile_for_prompt(make_profile(), budget_tokens=500, privacy=True)
        assert "上海" not in text
        assert "revenue" in text  # schema stats still available
