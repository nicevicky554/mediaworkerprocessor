import os


def _env(name: str, default: str | None = None) -> str:
    value = os.environ.get(name, default)
    if value is None or value.strip() == "":
        raise RuntimeError(f"{name} is required by the media worker.")
    return value.strip()


class Settings:
    supabase_url: str = _env("SUPABASE_URL")
    supabase_secret_key: str = _env("SUPABASE_SECRET_KEY")
    processor_secret: str = _env("MEDIA_PROCESSOR_SECRET")
    port: int = int(os.environ.get("PORT", "8080"))
    work_dir: str = os.environ.get("MEDIA_WORK_DIR", "/tmp/enforce-media")
    max_concurrent_jobs: int = int(os.environ.get("MEDIA_MAX_CONCURRENT_JOBS", "1"))

    # FFmpeg settings
    waveform_buckets: int = int(os.environ.get("WAVEFORM_BUCKETS", "900"))
    fingerprint_fps: int = int(os.environ.get("FINGERPRINT_FPS", "4"))
    analyze_sample_rate: int = 8000


settings = Settings()
