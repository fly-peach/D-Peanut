"""Spike B: kernel_pool minimal - subprocess kernel, execute/capture/interrupt,
DataFrame persistence across execute() calls (roadmap M0 Spike B)."""

import pytest

from data_agent.exec.kernel_pool import KernelPool


@pytest.fixture()
def pool():
    p = KernelPool()
    yield p
    p.shutdown_all()


def test_dataframe_persists_across_executes(pool):
    sid = pool.start()
    r1 = pool.execute(sid, "import pandas as pd\nx = pd.DataFrame({'a': [1, 2, 3]})")
    assert r1.ok, r1.error
    r2 = pool.execute(sid, "print(int(x['a'].sum()))")
    assert r2.ok, r2.error
    assert "6" in r2.stdout


def test_error_capture(pool):
    sid = pool.start()
    r = pool.execute(sid, "1 / 0")
    assert not r.ok
    assert "ZeroDivisionError" in r.error


def test_interrupt_then_recover(pool):
    sid = pool.start()
    r = pool.execute(sid, "import time; time.sleep(30)", timeout_s=2.0)
    assert not r.ok
    assert "interrupt" in r.error.lower()
    # kernel must be usable again right after the interrupt
    r2 = pool.execute(sid, "print('alive')")
    assert r2.ok, r2.error
    assert "alive" in r2.stdout
