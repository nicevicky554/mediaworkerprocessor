from __future__ import annotations

import os
from contextlib import asynccontextmanager

from fastapi import BackgroundTasks, Depends, FastAPI, HTTPException

from .audio.inspect import ffmpeg_available
from .config import settings
from .jobs import run_job
from .security import require_processor_secret
from .storage.client import get_job

# Run with a single uvicorn worker by default: media work is CPU bound and
# FFmpeg already uses multiple threads. Scale horizontally with more instances
# rather than more workers inside one small container.


@asynccontextmanager
async def lifespan(_: FastAPI):
    os.makedirs(settings.work_dir, exist_ok=True)
    yield


app = FastAPI(
    title="ENFORCE AI media worker",
    version="1.0.0",
    description="FFmpeg-based inspection, waveform, fingerprint and crop jobs.",
    lifespan=lifespan,
)


@app.get("/health")
def health(_: None = Depends(require_processor_secret)) -> dict:
    return {
        "ok": True,
        "ffmpeg": ffmpeg_available(),
        "maxConcurrentJobs": settings.max_concurrent_jobs,
    }


@app.post("/jobs/{job_id}/run")
async def run(
    job_id: str,
    background: BackgroundTasks,
    _: None = Depends(require_processor_secret),
) -> dict:
    job = get_job(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found.")
    if job["status"] not in ("queued", "processing"):
        return {"accepted": False, "message": f"Job is already {job['status']}."}
    if not ffmpeg_available():
        raise HTTPException(status_code=503, detail="FFmpeg is not installed in the worker.")

    # Starlette runs background tasks after the response is sent, so the API
    # call returns immediately while FFmpeg keeps working.
    background.add_task(run_job, job_id)
    return {"accepted": True, "message": "Job accepted."}


@app.get("/")
def root() -> dict:
    return {"service": "enforce-media-worker", "docs": "/docs"}
