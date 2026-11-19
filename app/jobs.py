from __future__ import annotations

import os
import shutil
import tempfile
from datetime import datetime, timezone
from typing import Any

from .audio.crop import crop_audio
from .audio.fingerprint import envelope_fingerprint
from .audio.inspect import inspect
from .audio.waveform import waveform_peaks
from .config import settings
from .storage.client import (
    db,
    download_object,
    notify,
    update_job,
    upload_object,
)

MAX_ATTEMPTS = 3


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _verified_music(job: dict[str, Any]) -> dict[str, Any] | None:
    """Confirm the job's source belongs to the same user that owns the job."""
    music_id = job.get("music_id")
    if not music_id:
        return None
    response = (
        db()
        .table("protected_music")
        .select("id, user_id, title, storage_path, processing_status")
        .eq("id", music_id)
        .maybe_single()
        .execute()
    )
    music = response.data if response else None
    if not music:
        raise RuntimeError("The referenced recording no longer exists.")
    if music["user_id"] != job["user_id"]:
        raise PermissionError("The job does not own the referenced recording.")
    if music.get("storage_path") and music["storage_path"] != job["storage_path"]:
        raise PermissionError("The job path does not match the recording's stored object.")
    return music


def _fail(job: dict[str, Any], code: str, message: str) -> None:
    update_job(
        job["id"],
        {
            "status": "failed",
            "error_code": code,
            "error_message": message[:800],
            "completed_at": now_iso(),
        },
    )


def run_job(job_id: str) -> None:
    job = (
        db().table("processing_jobs").select("*").eq("id", job_id).maybe_single().execute()
    ).data
    if not job:
        return
    if job["status"] not in ("queued", "processing"):
        return
    if job.get("cancel_requested"):
        update_job(job_id, {"status": "cancelled", "completed_at": now_iso()})
        return

    attempts = int(job.get("attempts") or 0) + 1
    if attempts > MAX_ATTEMPTS:
        _fail(job, "MEDIA_RETRY_LIMIT", "This job exceeded the retry limit.")
        return

    update_job(
        job_id,
        {
            "status": "processing",
            "attempts": attempts,
            "started_at": now_iso(),
            "progress": 1,
            "error_code": None,
            "error_message": None,
        },
    )

    os.makedirs(settings.work_dir, exist_ok=True)
    workdir = tempfile.mkdtemp(prefix="job-", dir=settings.work_dir)
    local_source = None
    try:
        music = _verified_music(job) if job.get("music_id") else None
        local_source = download_object(job["storage_bucket"], job["storage_path"])
        update_job(job_id, {"progress": 10})

        if job["kind"] == "inspect":
            result = inspect(local_source)
            update_job(job_id, {"status": "completed", "progress": 100, "result": result,
                                "completed_at": now_iso()})
            return

        if job["kind"] == "waveform":
            result = waveform_peaks(local_source)
            update_job(job_id, {"status": "completed", "progress": 100, "result": result,
                                "completed_at": now_iso()})
            return

        if job["kind"] == "fingerprint":
            params = job.get("params") or {}
            fingerprint = envelope_fingerprint(
                local_source,
                float(params.get("startSeconds") or 0),
                float(params.get("endSeconds") or 0) or None,
            )
            if music:
                db().table("protected_music").update(
                    {
                        "fingerprint": fingerprint["fingerprint"],
                        "frames_per_second": fingerprint["framesPerSecond"],
                        "duration": fingerprint["duration"],
                        "clip_start": fingerprint["clipStart"],
                        "clip_end": fingerprint["clipEnd"],
                        "fingerprint_version": "envelope-v1",
                        "processing_status": "ready",
                        "processing_error": None,
                        "fingerprint_updated_at": now_iso(),
                        "analysis_source": "media-worker",
                    }
                ).eq("id", music["id"]).execute()
            update_job(
                job_id,
                {
                    "status": "completed",
                    "progress": 100,
                    "result": {
                        "frames": len(fingerprint["fingerprint"]),
                        "framesPerSecond": fingerprint["framesPerSecond"],
                        "duration": fingerprint["duration"],
                    },
                    "completed_at": now_iso(),
                },
            )
            return

        if job["kind"] == "crop":
            params = job.get("params") or {}
            start = float(params.get("startSeconds") or 0)
            end = float(params.get("endSeconds") or 0)
            destination = os.path.join(workdir, "crop.mp3")

            def progress(percent: int) -> None:
                current = (
                    db()
                    .table("processing_jobs")
                    .select("cancel_requested")
                    .eq("id", job_id)
                    .maybe_single()
                    .execute()
                )
                if current.data and current.data.get("cancel_requested"):
                    raise RuntimeError("cancelled by user")
                update_job(job_id, {"progress": 10 + int(percent * 0.8)})

            info = crop_audio(local_source, destination, start, end, progress)
            object_path = f"{job['user_id']}/crops/{job_id}.mp3"
            upload_object("protected-media", object_path, destination, "audio/mpeg")
            if music:
                db().table("protected_music").update(
                    {
                        "crop_storage_path": object_path,
                        "crop_start_seconds": start,
                        "crop_end_seconds": end,
                    }
                ).eq("id", music["id"]).execute()
            update_job(
                job_id,
                {
                    "status": "completed",
                    "progress": 100,
                    "result_bucket": "protected-media",
                    "result_path": object_path,
                    "result": info,
                    "completed_at": now_iso(),
                },
            )
            notify(
                job["user_id"],
                "Audio crop completed",
                f"Your {info['duration']:.1f}s excerpt is ready to download.",
                "system",
            )
            return

        raise RuntimeError(f"Unsupported job kind: {job['kind']}")
    except Exception as error:  # noqa: BLE001 - surface a structured job error
        message = str(error)
        if "cancelled by user" in message:
            update_job(job_id, {"status": "cancelled", "completed_at": now_iso()})
            return
        if isinstance(error, PermissionError):
            _fail(job, "MEDIA_FORBIDDEN", message)
        elif isinstance(error, FileNotFoundError):
            _fail(job, "MEDIA_SOURCE_MISSING", message)
        else:
            _fail(job, "MEDIA_PROCESSING_FAILED", message)
        notify(
            job["user_id"],
            "Audio processing failed",
            f"The {job['kind']} job failed: {message[:180]}",
            "system",
        )
    finally:
        if local_source and os.path.exists(local_source):
            os.remove(local_source)
        shutil.rmtree(workdir, ignore_errors=True)
