"""Cloud Functions for Firebase Gen-2 entrypoints (HTTP streaming API + Cloud Storage document trigger)."""

from __future__ import annotations

import os
from typing import Any

import firebase_admin
from firebase_functions import https_fn, options, storage_fn
from firebase_functions.core import init

from app.routes import create_flask_app, process_uploaded_document_blob
from app.store import FirestoreRepository
from tranx_core import init_tranx_core

options.set_global_options(region="asia-southeast2")

_FLASK_APP = None
_REPO: FirestoreRepository | None = None


def _env_api_key() -> str | None:
    for var in ("LLM_KEY", "GEMINI_API_KEY", "JPTRANS_LLM_API_KEY"):
        val = (os.environ.get(var) or "").strip()
        if val:
            return val
    return None


@init
def bootstrap_runtime() -> None:
    """Deferred runtime init so Firebase CLI function discovery completes instantaneously."""
    global _FLASK_APP, _REPO
    if not firebase_admin._apps:
        firebase_admin.initialize_app()
    manifest_hash = init_tranx_core(_env_api_key)
    _REPO = FirestoreRepository(env_api_key_getter=_env_api_key)
    _FLASK_APP = create_flask_app(_REPO, manifest_hash=manifest_hash)


def _ensure_ready() -> tuple[Any, FirestoreRepository]:
    if _FLASK_APP is None or _REPO is None:
        bootstrap_runtime()
    assert _FLASK_APP is not None and _REPO is not None
    return _FLASK_APP, _REPO


@https_fn.on_request(
    region="asia-southeast2",
    memory=options.MemoryOption.MB_512,
    cpu=1,
    concurrency=20,
    min_instances=0,
    max_instances=2,
    timeout_sec=540,
)
def api(req: https_fn.Request) -> https_fn.Response:
    flask_app, _ = _ensure_ready()
    env = dict(req.environ)
    path_info = env.get("PATH_INFO", "")
    if path_info.startswith("/api/v1"):
        env["PATH_INFO"] = path_info[4:]
    with flask_app.request_context(env):
        return flask_app.full_dispatch_request()


@storage_fn.on_object_finalized(
    region="asia-southeast2",
    memory=options.MemoryOption.GB_1,
    cpu=1,
    concurrency=1,
    min_instances=0,
    max_instances=1,
    timeout_sec=540,
)
def on_document_uploaded(
    event: storage_fn.CloudEvent[storage_fn.StorageObjectData],
) -> None:
    _, repo = _ensure_ready()
    object_name = event.data.name or ""
    if not object_name.startswith("uploads/"):
        return
    process_uploaded_document_blob(repo, object_name=object_name)
