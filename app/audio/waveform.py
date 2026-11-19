from __future__ import annotations

import array
import math
import subprocess

from ..config import settings
from .inspect import inspect


def _decode_pcm(path: str, sample_rate: int, start: float | None = None, duration: float | None = None):
    command = ["ffmpeg", "-v", "error"]
    if start is not None:
        command += ["-ss", f"{max(0.0, start):.3f}"]
    command += ["-i", path]
    if duration is not None:
        command += ["-t", f"{max(0.1, duration):.3f}"]
    command += [
        "-vn",
        "-ac",
        "1",
        "-ar",
        str(sample_rate),
        "-f",
        "s16le",
        "-",
    ]
    result = subprocess.run(command, capture_output=True, timeout=600)
    if result.returncode != 0:
        raise RuntimeError(f"FFmpeg decode failed: {result.stderr.decode()[:400]}")
    samples = array.array("h")
    samples.frombytes(result.stdout)
    return samples


def waveform_peaks(path: str) -> dict:
    """Return normalised RMS peaks (0..1) plus the probed duration."""
    info = inspect(path)
    samples = _decode_pcm(path, settings.analyze_sample_rate)
    buckets = max(32, min(settings.waveform_buckets, 2000))
    if len(samples) == 0:
        raise RuntimeError("The audio track is empty or could not be decoded.")

    bucket_size = max(1, len(samples) // buckets)
    peaks: list[float] = []
    for index in range(0, len(samples), bucket_size):
        chunk = samples[index : index + bucket_size]
        if not chunk:
            continue
        energy = math.sqrt(sum(sample * sample for sample in chunk) / len(chunk)) / 32768.0
        peaks.append(round(min(1.0, energy * 3.2), 4))

    loudest = max(peaks) if peaks else 0.0
    if loudest > 0:
        peaks = [round(peak / loudest, 4) for peak in peaks]

    return {"duration": info["duration"], "peaks": peaks}
