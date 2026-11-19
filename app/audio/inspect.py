from __future__ import annotations

import json
import shutil
import subprocess


def ffmpeg_available() -> bool:
    return shutil.which("ffmpeg") is not None and shutil.which("ffprobe") is not None


def inspect(path: str) -> dict:
    """Return duration, codec and container details using FFprobe."""
    if not ffmpeg_available():
        raise RuntimeError("FFmpeg/FFprobe is not installed in the worker image.")

    result = subprocess.run(
        [
            "ffprobe",
            "-v",
            "error",
            "-print_format",
            "json",
            "-show_format",
            "-show_streams",
            path,
        ],
        capture_output=True,
        text=True,
        timeout=60,
    )
    if result.returncode != 0:
        raise RuntimeError(f"FFprobe failed: {result.stderr.strip()[:400]}")

    payload = json.loads(result.stdout or "{}")
    audio_stream = next(
        (stream for stream in payload.get("streams", []) if stream.get("codec_type") == "audio"),
        None,
    )
    duration = float(payload.get("format", {}).get("duration") or 0)
    if duration <= 0 and audio_stream:
        duration = float(audio_stream.get("duration") or 0)

    return {
        "duration": duration,
        "format": payload.get("format", {}).get("format_name"),
        "bit_rate": int(payload.get("format", {}).get("bit_rate") or 0),
        "codec": audio_stream.get("codec_name") if audio_stream else None,
        "sample_rate": int(audio_stream.get("sample_rate") or 0) if audio_stream else 0,
        "channels": int(audio_stream.get("channels") or 0) if audio_stream else 0,
    }
