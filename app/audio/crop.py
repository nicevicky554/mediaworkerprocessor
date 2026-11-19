from __future__ import annotations

import os
import subprocess


def crop_audio(
    source: str,
    destination: str,
    start: float,
    end: float,
    on_progress=None,
) -> dict:
    """Trim [start, end) to MP3.

    Re-encoding is used because stream copy at arbitrary timestamps is frame
    aligned and would silently include up to a second of extra audio.
    """
    if start < 0:
        raise ValueError("The crop start cannot be negative.")
    if end <= start:
        raise ValueError("The crop end must be after the start.")

    os.makedirs(os.path.dirname(destination), exist_ok=True)
    duration = max(0.1, end - start)
    command = [
        "ffmpeg",
        "-hide_banner",
        "-v",
        "error",
        "-nostdin",
        "-ss",
        f"{start:.3f}",
        "-i",
        source,
        "-t",
        f"{duration:.3f}",
        "-vn",
        "-c:a",
        "libmp3lame",
        "-q:a",
        "2",
        "-progress",
        "pipe:1",
        "-y",
        destination,
    ]

    process = subprocess.Popen(
        command, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True
    )
    assert process.stdout is not None
    try:
        for line in process.stdout:
            if line.startswith("out_time_ms=") and on_progress:
                try:
                    microseconds = int(line.split("=", 1)[1].strip())
                    percent = min(99, int((microseconds / 1_000_000) / duration * 100))
                    on_progress(max(1, percent))
                except ValueError:
                    continue
    except Exception:
        process.terminate()
        try:
            process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            process.kill()
        raise
    stderr = process.stderr.read() if process.stderr else ""
    process.wait()
    if process.returncode != 0:
        raise RuntimeError(f"FFmpeg crop failed: {stderr[:400]}")

    size = os.path.getsize(destination)
    if size == 0:
        raise RuntimeError("FFmpeg produced an empty file.")
    return {"bytes": size, "duration": duration, "start": start, "end": end}
