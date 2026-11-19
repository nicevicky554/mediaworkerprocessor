# ENFORCE AI media worker

FFmpeg/FFprobe service for audio inspection, waveform peaks, fingerprints and
crop exports. It is **not** a Vercel function: Vercel cannot keep FFmpeg jobs
running, so this service is deployed separately (Fly.io, Railway, Render,
Google Cloud Run, or any container host).

## What it does

| Endpoint | Purpose |
| --- | --- |
| `GET /health` | Secret-protected health probe (reports FFmpeg availability) |
| `POST /jobs/{jobId}/run` | Accepts a queued job and processes it in the background |

The worker never accepts file paths or user ids from a request. It loads the
job row from Postgres with the service key, verifies that the linked
`protected_music` row belongs to the same user, downloads the object to a
temporary directory, does the work, uploads results back to Supabase Storage and
updates the job row.

## Environment variables

| Variable | Required | Notes |
| --- | --- | --- |
| `SUPABASE_URL` | yes | Same project as the web app |
| `SUPABASE_SECRET_KEY` | yes | Service/secret key — server only |
| `MEDIA_PROCESSOR_SECRET` | yes | Shared secret, identical to Vercel's value |
| `PORT` | no | Defaults to `8080` |
| `WAVEFORM_BUCKETS` | no | Defaults to `900` |
| `FINGERPRINT_FPS` | no | Defaults to `4` |
| `MEDIA_MAX_CONCURRENT_JOBS` | no | Informational; run one worker per instance |

## Run locally

```bash
cd media-worker
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
export SUPABASE_URL=... SUPABASE_SECRET_KEY=... MEDIA_PROCESSOR_SECRET=...
uvicorn app.main:app --reload
```

FFmpeg must be installed (`brew install ffmpeg` / `apt-get install ffmpeg`).
Without it `/health` returns `ffmpeg: false` and jobs are rejected with 503.

## Deploy

```bash
docker build -t enforce-media-worker .
docker run -p 8080:8080 \
  -e SUPABASE_URL=... \
  -e SUPABASE_SECRET_KEY=... \
  -e MEDIA_PROCESSOR_SECRET=... \
  enforce-media-worker
```

Set `MEDIA_PROCESSOR_URL` on Vercel to the public HTTPS origin of this service
(no trailing slash) and the same `MEDIA_PROCESSOR_SECRET`. The Vercel API calls
`POST {MEDIA_PROCESSOR_URL}/jobs/{id}/run`; the browser never talks to the
worker.

## Hosting reality check

This service needs a **persistent process** because jobs continue after the HTTP
response returns. Scale-to-zero hosts can throttle or stop the container once the
response is sent, which strands jobs.

| Host | Process model | Free-plan caveats |
| --- | --- | --- |
| Fly.io | Long-running Machines, optional auto-stop | No permanent free allowance for new organisations; usage-based billing. Best fit if you keep one small Machine always on. |
| Railway | Long-running container | Trial/limited monthly credit; usage-based after that. Persistent process and ephemeral disk; add a volume for scratch space if needed. |
| Render | Web service | The free web service **sleeps after inactivity** and cold-starts on the next request; 512 MB RAM class and ephemeral disk. A sleeping worker can miss a dispatch. |
| Google Cloud Run | Request-driven, scale to zero | Free monthly request/vCPU-second allowance. CPU is throttled after the response unless CPU is always allocated, so the background job can stall; use minimum instances + always-on CPU, or a request that waits for the job. |

All of these have limited CPU/RAM and ephemeral local disk. None can honestly
promise unlimited large-audio processing: a 100 MB master needs download + FFmpeg
time + upload, and a 512 MB instance may fail on long jobs. Process one job at a
time and scale instances, not concurrency per instance. Check the provider's
current pricing page before relying on a free tier.

## Limits and honesty

- Fingerprints are envelope-based (`envelope-v1`) leads, not proof of copying.
- Crops re-encode to MP3 (`libmp3lame -q:a 2`) because stream copy at arbitrary
  timestamps is frame aligned.
- One container processes one job at a time; scale by running more instances.
- Temporary files are deleted after each job, including failures.
