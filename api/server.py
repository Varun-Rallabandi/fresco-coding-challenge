"""HTTP API with a background job queue.

    uvicorn api.server:app --reload

    POST /jobs                 upload a PDF -> {"job_id": ...} immediately
    GET  /jobs/{id}            status: queued | running | done | failed (+ run stats)
    GET  /jobs/{id}/result     the extracted hardware sets (JSON)
    POST /corrections          record a reviewer's fix to one field
    GET  /corrections/summary  which fields get corrected most

Why a queue: a 4,000-page project manual takes ~45 s. Instead of holding the
HTTP request open, the upload returns a job id right away and a background
worker does the work. Here the queue is an in-process asyncio.Queue with a few
worker tasks; the extraction itself runs in a thread so the server stays
responsive. To scale out you would swap the queue for Redis/SQS and run the
workers as separate processes; the API and the job table would not change.
"""
from __future__ import annotations

import asyncio
import shutil
import time
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, File, HTTPException, UploadFile
from pydantic import BaseModel

from hwsets.cache import Cache, file_fingerprint
from hwsets.extract import extract
from hwsets.store import Store

UPLOADS = Path(__file__).resolve().parents[1] / ".cache" / "uploads"
WORKERS = 2

store = Store()
cache = Cache()
queue: asyncio.Queue[str] = asyncio.Queue()


async def worker(n: int) -> None:
    while True:
        job_id = await queue.get()
        job = store.get_job(job_id)
        try:
            store.update_job(job_id, status="running", started=time.time())
            key = cache.result_key(job["pdf_path"], None, bool(job["ai"]))
            hit = cache.get_result(key) is not None
            # CPU-heavy PDF work runs in a thread so the event loop keeps serving requests.
            await asyncio.to_thread(extract, job["pdf_path"], None, bool(job["ai"]), cache)
            store.update_job(job_id, status="done", finished=time.time(), result_key=key, cache_hit=int(hit))
        except Exception as e:  # a bad PDF fails its own job, never the worker
            store.update_job(job_id, status="failed", finished=time.time(), error=str(e)[:500])
        finally:
            queue.task_done()


@asynccontextmanager
async def lifespan(app: FastAPI):
    for job in store.unfinished_jobs():  # survive restarts: requeue anything unfinished
        await queue.put(job["id"])
    tasks = [asyncio.create_task(worker(i)) for i in range(WORKERS)]
    yield
    for t in tasks:
        t.cancel()


app = FastAPI(title="Hardware Set Extractor", lifespan=lifespan)


@app.get("/health")
def health():
    return {"ok": True, "queued": queue.qsize()}


@app.post("/jobs")
async def create_job(file: UploadFile = File(...), ai: bool = False):
    if not (file.filename or "").lower().endswith(".pdf"):
        raise HTTPException(400, "upload a PDF")
    UPLOADS.mkdir(parents=True, exist_ok=True)
    tmp = UPLOADS / f"incoming-{time.time_ns()}.pdf"
    with tmp.open("wb") as fh:
        shutil.copyfileobj(file.file, fh)
    # Store by content fingerprint: the same PDF uploaded twice is one file (and one cache entry).
    dest = UPLOADS / f"{file_fingerprint(tmp)}.pdf"
    tmp.replace(dest)
    job_id = store.create_job(file.filename, str(dest), ai)
    await queue.put(job_id)
    return {"job_id": job_id, "status": "queued"}


@app.get("/jobs")
def list_jobs():
    return store.list_jobs()


@app.get("/jobs/{job_id}")
def get_job(job_id: str):
    job = store.get_job(job_id)
    if not job:
        raise HTTPException(404, "no such job")
    if job["status"] == "done":
        result = cache.get_result(job["result_key"])
        job["stats"] = result.get("stats") if result else None
    return job


@app.get("/jobs/{job_id}/result")
def get_result(job_id: str):
    job = store.get_job(job_id)
    if not job:
        raise HTTPException(404, "no such job")
    if job["status"] != "done":
        raise HTTPException(409, f"job is {job['status']}")
    return cache.get_result(job["result_key"])


class Correction(BaseModel):
    source_file: str
    set_number: str
    comp_index: int
    field: str
    old_value: str | int | None = None
    new_value: str | int | None = None


@app.post("/corrections")
def add_correction(c: Correction):
    store.add_correction(c.source_file, c.set_number, c.comp_index, c.field, c.old_value, c.new_value)
    return {"ok": True}


@app.get("/corrections/summary")
def correction_summary():
    return store.correction_summary()
