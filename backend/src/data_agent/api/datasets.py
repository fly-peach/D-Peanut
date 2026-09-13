"""Datasets control plane (design-architecture §3.1 / data-catalog change).

Registration returns immediately (pending); scan+profile run as background tasks.
Jail violations are 400, name collisions 409. Profile/preview read the cached
profile; privacy datasets never expose raw rows.
"""

from __future__ import annotations

from typing import Any, Literal

from fastapi import APIRouter, BackgroundTasks, HTTPException, Query, Request
from pydantic import BaseModel

from ..catalog.models import Dataset, DatasetBrief, DatasetKind, TableProfile
from ..catalog.pipeline import RegisterError
from ..catalog.registry import DuplicateNameError, NotFoundError
from ..catalog.sampler import effective_privacy, preview_from_df, preview_summary

router = APIRouter(prefix="/datasets", tags=["datasets"])


class DatasetRegister(BaseModel):
    kind: Literal["file", "folder", "sql"]
    path: str | None = None  # file
    root: str | None = None  # folder
    extensions: list[str] | None = None
    conn_target: str | None = None  # sql: sqlite file path (stored as secret)
    table: str | None = None
    name: str | None = None
    description: str = ""
    privacy_mode: bool | None = None


class DatasetPatch(BaseModel):
    name: str | None = None
    description: str | None = None
    privacy_mode: bool | None = None
    tags: list[str] | None = None


def _pipeline(request: Request):
    return request.app.state.catalog


def _repo(request: Request):
    return request.app.state.catalog.repo


def _err(status: int, msg: str) -> HTTPException:
    return HTTPException(status_code=status, detail=msg)


@router.post("", status_code=201)
def register(
    body: DatasetRegister, request: Request, background: BackgroundTasks
) -> dict[str, Any]:
    pipe = _pipeline(request)
    try:
        if body.kind == "file":
            if not body.path:
                raise RegisterError("file kind requires path")
            created = pipe.register_file(body.path, body.name, body.privacy_mode)
        elif body.kind == "folder":
            if not body.root:
                raise RegisterError("folder kind requires root")
            created = [pipe.register_folder(body.root, body.name, body.extensions,
                                            body.privacy_mode)]
        else:
            if not body.conn_target or not body.table:
                raise RegisterError("sql kind requires conn_target and table")
            created = [pipe.register_sql(body.conn_target, body.table, body.name,
                                         body.privacy_mode)]
    except RegisterError as e:
        raise _err(400, str(e)) from e
    except DuplicateNameError as e:
        raise _err(409, str(e)) from e
    except ValueError as e:  # JailError et al.
        raise _err(400, str(e)) from e
    for ds in created:
        if body.description:
            ds.description = body.description
            _repo(request).update(ds)
        background.add_task(pipe.run, ds.id)
    return {"datasets": [c.id for c in created]}


@router.get("")
def list_datasets(request: Request, kind: DatasetKind | None = None) -> list[DatasetBrief]:
    return _repo(request).list(kind)


@router.get("/{dataset_id}")
def get_dataset(dataset_id: str, request: Request) -> Dataset:
    try:
        return _repo(request).get(dataset_id)
    except NotFoundError as e:
        raise _err(404, "dataset not found") from e


@router.post("/{dataset_id}/rescan", status_code=202)
def rescan(dataset_id: str, request: Request, background: BackgroundTasks) -> dict[str, str]:
    pipe = _pipeline(request)
    ds = get_dataset(dataset_id, request)
    background.add_task(pipe.rescan, ds.id)
    return {"status": "rescanning", "id": ds.id}


@router.get("/{dataset_id}/profile")
def profile(dataset_id: str, request: Request) -> TableProfile:
    ds = get_dataset(dataset_id, request)
    prof = _repo(request).get_profile(ds.id, ds.revision)
    if prof is None:
        raise _err(409, f"profile not ready (status={ds.profile_status.value})")
    return prof


@router.get("/{dataset_id}/preview")
def preview(dataset_id: str, request: Request,
            n: int = Query(default=20, ge=1, le=50)) -> dict[str, Any]:
    ds = get_dataset(dataset_id, request)
    repo = _repo(request)
    if ds.kind is DatasetKind.folder:
        raise _err(400, "folders carry no rows; preview a child dataset")
    if effective_privacy(ds, _pipeline(request).settings):
        prof = repo.get_profile(ds.id, ds.revision)
        if prof is None:
            raise _err(409, "profile not ready")
        return preview_summary(prof)
    from ..catalog import reader

    kwargs: dict[str, Any] = {}
    if ds.kind == DatasetKind.sql:
        kwargs["conn_target"] = _pipeline(request).settings.secrets.get(ds.meta.conn_ref)
    limit = min(n, _pipeline(request).preview_limit())
    try:
        df = reader.read_dataset(ds, limit=limit + 1, **kwargs)
    except FileNotFoundError as e:
        raise _err(409, str(e)) from e
    return preview_from_df(df, limit)


@router.patch("/{dataset_id}")
def patch_dataset(dataset_id: str, body: DatasetPatch, request: Request) -> Dataset:
    repo = _repo(request)
    ds = get_dataset(dataset_id, request)
    if body.name is not None:
        ds.name = body.name
    if body.description is not None:
        ds.description = body.description
    if body.privacy_mode is not None:
        ds.privacy_mode = body.privacy_mode
        # privacy toggle invalidates the cached view: re-derive without re-profiling
        prof = repo.get_profile(ds.id, ds.revision)
        if prof is not None:
            _apply_privacy(ds, prof, repo, request)
    if body.tags is not None:
        ds.tags = body.tags
    from ..catalog.registry import DuplicateNameError

    try:
        return repo.update(ds)
    except DuplicateNameError as e:
        raise _err(409, str(e)) from e


def _apply_privacy(ds: Dataset, prof: TableProfile, repo, request: Request) -> None:
    p = prof.model_copy(deep=True)
    if effective_privacy(ds, _pipeline(request).settings):
        for c in p.columns:
            c.sample_values = []
            c.top_values = []
    repo.put_profile(ds, p)


@router.delete("/{dataset_id}", status_code=204)
def delete_dataset(dataset_id: str, request: Request) -> None:
    repo = _repo(request)
    ds = get_dataset(dataset_id, request)
    refs = repo.referrers(dataset_id)
    if refs:
        raise _err(409, f"referenced by: {', '.join(refs)}")
    # folders cascade to their children
    for child in repo.children(ds.id):
        repo.delete(child.id)
    # N2 hook: assets referencing this dataset must also block deletion.
    repo.delete(dataset_id)
