from __future__ import annotations

import os
import tempfile
from typing import Any

from supabase import Client, create_client

from ..config import settings

_client: Client | None = None


def db() -> Client:
    global _client
    if _client is None:
        _client = create_client(settings.supabase_url, settings.supabase_secret_key)
    return _client


def download_object(bucket: str, path: str) -> str:
    """Download a private object to a temporary file and return its path."""
    os.makedirs(settings.work_dir, exist_ok=True)
    suffix = os.path.splitext(path)[1] or ".bin"
    handle = tempfile.NamedTemporaryFile(
        delete=False, suffix=suffix, dir=settings.work_dir, prefix="src-"
    )
    handle.close()
    data = db().storage.from_(bucket).download(path)
    with open(handle.name, "wb") as out:
        out.write(data)
    return handle.name


def upload_object(bucket: str, path: str, file_path: str, content_type: str) -> None:
    with open(file_path, "rb") as source:
        db().storage.from_(bucket).upload(
            path,
            source,
            file_options={"content-type": content_type, "upsert": "true"},
        )


def update_job(job_id: str, patch: dict[str, Any]) -> None:
    db().table("processing_jobs").update(patch).eq("id", job_id).execute()


def get_job(job_id: str) -> dict[str, Any] | None:
    response = (
        db().table("processing_jobs").select("*").eq("id", job_id).maybe_single().execute()
    )
    return response.data if response else None


def notify(user_id: str, title: str, message: str, kind: str = "system") -> None:
    try:
        db().table("notifications").insert(
            {
                "user_id": user_id,
                "title": title,
                "message": message,
                "notification_type": kind,
                "email_status": "skipped",
                "telegram_status": "skipped",
            }
        ).execute()
    except Exception as error:  # notification failure must not fail the job
        print(f"[worker] notification failed: {error}")
