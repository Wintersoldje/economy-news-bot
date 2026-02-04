from __future__ import annotations

import os
import uuid
import time
import threading
import subprocess
from dataclasses import dataclass
from typing import Dict, Optional

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from pydantic import BaseModel


app = FastAPI(title="Script/Render MVP")

# Dev CORS: allow all. Tighten in production.
app.add_middleware(
    CORSMiddleware,
    allow_origins=["https://wintersoldje.github.io"],
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)


TMP_DIR = "/tmp/mvp"
# NOTE: MVP stores generated files in local /tmp.
# In production (e.g., Cloud Run), replace this with GCS or another durable storage.
os.makedirs(TMP_DIR, exist_ok=True)


@dataclass
class Job:
    job_id: str
    status: str  # queued|running|done|failed
    type: str
    created_at: float
    video_path: Optional[str] = None
    error: Optional[str] = None


JOBS: Dict[str, Job] = {}
JOBS_LOCK = threading.Lock()


class ScriptRequest(BaseModel):
    type: str  # short|long


class RenderRequest(BaseModel):
    type: str  # short|long


def _validate_type(t: str) -> str:
    if t not in ("short", "long"):
        raise HTTPException(status_code=400, detail="type must be 'short' or 'long'")
    return t


def _dummy_script(t: str) -> str:
    if t == "short":
        return (
            "[숏츠 대본]\n"
            "- 0~2초: 훅(문제 제기)\n"
            "- 2~7초: 핵심 1가지\n"
            "- 7~10초: 결론 + CTA\n"
            "\n"
            "예시: '이 설정 하나로 생산성이 2배 됩니다. 바로...'")
    return (
        "[롱폼 대본]\n"
        "1) 오프닝: 오늘 다룰 주제와 기대효과\n"
        "2) 본론: 배경 -> 사례 -> 단계별 방법\n"
        "3) 요약: 핵심 3가지 정리\n"
        "4) 마무리: 다음 영상 예고 + CTA\n"
    )


@app.post("/api/script")
def create_script(req: ScriptRequest):
    t = _validate_type(req.type)
    script = _dummy_script(t)

    script_id = str(uuid.uuid4())
    path = os.path.join(TMP_DIR, f"script_{script_id}.txt")
    with open(path, "w", encoding="utf-8") as f:
        f.write(script)

    return {
        "type": t,
        "script": script,
        "download_url": f"/api/download/script/{script_id}",
    }


@app.get("/api/download/script/{script_id}")
def download_script(script_id: str):
    path = os.path.join(TMP_DIR, f"script_{script_id}.txt")
    if not os.path.exists(path):
        raise HTTPException(status_code=404, detail="script not found")
    return FileResponse(path, media_type="text/plain", filename=f"script_{script_id}.txt")


def _render_worker(job_id: str, t: str):
    with JOBS_LOCK:
        job = JOBS.get(job_id)
        if not job:
            return
        job.status = "running"

    out_path = os.path.join(TMP_DIR, f"video_{job_id}.mp4")

    # Create dummy video using ffmpeg: 10 seconds solid color + silent audio.
    # Requires ffmpeg in PATH.
    cmd = [
        "ffmpeg",
        "-y",
        "-f",
        "lavfi",
        "-i",
        "color=c=blue:s=1280x720:d=10",
        "-f",
        "lavfi",
        "-i",
        "anullsrc=r=44100:cl=stereo",
        "-shortest",
        "-c:v",
        "libx264",
        "-pix_fmt",
        "yuv420p",
        "-c:a",
        "aac",
        out_path,
    ]

    try:
        proc = subprocess.run(cmd, capture_output=True, text=True, check=False)
        if proc.returncode != 0:
            raise RuntimeError((proc.stderr or proc.stdout or "ffmpeg failed").strip())

        with JOBS_LOCK:
            job = JOBS.get(job_id)
            if job:
                job.status = "done"
                job.video_path = out_path

    except Exception as e:
        with JOBS_LOCK:
            job = JOBS.get(job_id)
            if job:
                job.status = "failed"
                job.error = str(e)


@app.post("/api/render")
def start_render(req: RenderRequest):
    t = _validate_type(req.type)

    job_id = str(uuid.uuid4())
    job = Job(job_id=job_id, status="queued", type=t, created_at=time.time())

    with JOBS_LOCK:
        JOBS[job_id] = job

    th = threading.Thread(target=_render_worker, args=(job_id, t), daemon=True)
    th.start()

    return {"job_id": job_id}


@app.get("/api/render/status")
def render_status(job_id: str):
    with JOBS_LOCK:
        job = JOBS.get(job_id)
        if not job:
            raise HTTPException(status_code=404, detail="job not found")

        if job.status == "done":
            return {
                "job_id": job.job_id,
                "status": job.status,
                "video_url": f"/api/download/video/{job.job_id}",
            }
        if job.status == "failed":
            return {"job_id": job.job_id, "status": job.status, "error": job.error}

        return {"job_id": job.job_id, "status": job.status}


@app.get("/api/download/video/{job_id}")
def download_video(job_id: str):
    with JOBS_LOCK:
        job = JOBS.get(job_id)

    if not job:
        raise HTTPException(status_code=404, detail="job not found")
    if job.status != "done" or not job.video_path:
        raise HTTPException(status_code=400, detail="video not ready")
    if not os.path.exists(job.video_path):
        raise HTTPException(status_code=404, detail="video file missing")

    return FileResponse(job.video_path, media_type="video/mp4", filename=f"video_{job_id}.mp4")
