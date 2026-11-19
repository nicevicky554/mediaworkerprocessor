from __future__ import annotations

import math

from ..config import settings
from .inspect import inspect
from .waveform import _decode_pcm


def envelope_fingerprint(
    path: str,
    clip_start: float | None = None,
    clip_end: float | None = None,
) -> dict:
    """Build the same `envelope-v1` fingerprint the app compares against.

    Frames are RMS energies normalised by the loudest frame, sampled at
    FINGERPRINT_FPS. The comparison code tolerates time shifts, so no pitch or
    spectral step is needed for a first-pass lead.
    """
    info = inspect(path)
    total = info["duration"]
    start = max(0.0, clip_start or 0.0)
    end = clip_end if clip_end and clip_end > start else total
    end = min(end, total) if total > 0 else end
    if end - start < 4:
        raise RuntimeError("Select at least four seconds of audio to fingerprint.")

    fps = max(1, settings.fingerprint_fps)
    frame_size = max(1, settings.analyze_sample_rate // fps)
    samples = _decode_pcm(path, settings.analyze_sample_rate, start, end - start)
    if len(samples) < frame_size * 4:
        raise RuntimeError("The selected window is too short to fingerprint.")

    values: list[float] = []
    for offset in range(0, len(samples) - frame_size + 1, frame_size):
        frame = samples[offset : offset + frame_size]
        energy = math.sqrt(sum(sample * sample for sample in frame) / len(frame)) / 32768.0
        values.append(energy)

    loudest = max(values) if values else 0.0
    if loudest <= 0:
        raise RuntimeError("The audio appears to be silent, so it cannot be fingerprinted.")

    fingerprint = [round(min(1.0, value / loudest), 4) for value in values][:12000]
    return {
        "fingerprint": fingerprint,
        "framesPerSecond": fps,
        "duration": total,
        "clipStart": round(start, 3),
        "clipEnd": round(end, 3),
    }
