"""DoD #1-1 performance smoke: a 200-CSV mounted folder becomes fully addressable
and profiled quickly. Budget: 60s in-process (spec gives 5min wall for real data;
pytest-timeout caps us at 120s globally)."""

import time

from data_agent.catalog.pipeline import CatalogPipeline
from data_agent.catalog.registry import CatalogRepository
from data_agent.settings import SettingsService, Workspace

N_FILES = 200


def test_folder_200_files_under_60s(tmp_path):
    data = tmp_path / "data"
    root = data / "warehouse"
    root.mkdir(parents=True)
    payload = "month,city,revenue\n2021-01,A,10.5\n2021-02,B,20\n2021-03,C,30\n"
    for i in range(N_FILES):
        (root / f"part_{i:03d}.csv").write_text(payload, encoding="utf-8")

    ws = Workspace(data_root=data, workspace_root=tmp_path / "ws")
    ws.ensure_runtime()
    settings = SettingsService(ws)
    repo = CatalogRepository(ws.index_db)
    pipe = CatalogPipeline(repo, settings, ws)

    t0 = time.perf_counter()
    folder = pipe.register_folder(str(root))
    pipe.run(folder.id)  # synchronous: scan + expand + profile every child
    elapsed = time.perf_counter() - t0

    briefs = repo.list()
    children = [b for b in briefs if b.parent_id == folder.id]
    assert len(children) == N_FILES
    assert all(b.scan_status == "ready" and b.profile_status == "ready" for b in children)
    assert elapsed < 60, f"200-file scan+profile took {elapsed:.1f}s"
