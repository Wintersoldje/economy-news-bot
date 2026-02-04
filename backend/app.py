import os
import re
import json
import uuid
import time
import threading
import subprocess
from typing import Dict, Optional

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from pydantic import BaseModel

from openai import OpenAI
from news import fetch_news  # ✅ 상대 import 금지 (.news X)

# ----------------------------
# App / CORS
# ----------------------------
app = FastAPI()

app.add_middleware(
    CORSMiddleware,
    allow_origins=["https://wintersoldje.github.io"],
    allow_methods=["*"],
    allow_headers=["*"],
)

client = OpenAI()
MODEL = os.getenv("OPENAI_MODEL", "gpt-4o-mini")  # ✅ 원하는 모델: gpt-4o-mini

# ----------------------------
# Simple in-memory job store (MVP)
# - Cloud Run은 인스턴스가 재시작/스케일될 수 있어 영구 보장 X
# - MVP 테스트엔 OK, 운영은 GCS/Cloud Tasks로 옮기는 걸 추천
# ----------------------------
JOBS: Dict[str, Dict] = {}
JOBS_LOCK = threading.Lock()

TMP_DIR = "/tmp/econbot"
os.makedirs(TMP_DIR, exist_ok=True)

# ----------------------------
# Utils: TTS-friendly cleaning
# ----------------------------
_EMOJI_RE = re.compile(
    "["
    "\U0001F600-\U0001F64F"
    "\U0001F300-\U0001F5FF"
    "\U0001F680-\U0001F6FF"
    "\U0001F1E0-\U0001F1FF"
    "\U00002700-\U000027BF"
    "\U0001F900-\U0001F9FF"
    "\U00002600-\U000026FF"
    "]+",
    flags=re.UNICODE,
)

def tts_clean(text: str) -> str:
    """
    TTS에서 자주 깨지는 요소(이모지/특수문자/불필요한 기호/영문 약어 등)를 최소화.
    완벽한 정규화는 아니고, MVP용으로 '깨짐 방지'에 초점.
    """
    if not text:
        return ""

    # 이모지 제거
    text = _EMOJI_RE.sub("", text)

    # 흔한 특수문자 제거/치환
    # 금지: # * _ ~ > < {} [] = + ^ | \ / 등
    text = re.sub(r"[#*_~><{}\[\]=+\^|\\]", " ", text)
    text = text.replace("/", " 또는 ")

    # 따옴표/백틱 제거
    text = text.replace('"', "").replace("'", "").replace("`", "")

    # 통화/퍼센트 표기 치환
    text = text.replace("%", " 퍼센트 ")
    text = text.replace("$", " 달러 ")
    text = text.replace("₩", " 원 ")

    # 숫자 콤마 제거 (1,000 -> 1000)
    text = re.sub(r"(\d),(\d)", r"\1\2", text)

    # 과도한 공백 정리
    text = re.sub(r"\s+", " ", text).strip()

    return text

def split_sentences_kor(text: str) -> list[str]:
    """
    아주 단순한 문장 분리(마침표/물음표/느낌표 기준).
    """
    text = text.replace("다.", "다.\n").replace("요.", "요.\n")
    parts = re.split(r"[\n]+", text)
    parts = [p.strip() for p in parts if p.strip()]
    return parts

# ----------------------------
# Models
# ----------------------------
class ScriptReq(BaseModel):
    type: str  # "short" | "long"

class RenderReq(BaseModel):
    type: str  # "short" | "long"

# ----------------------------
# Health
# ----------------------------
@app.get("/health")
def health():
    return {"ok": True, "model": MODEL, "has_key": bool(os.getenv("OPENAI_API_KEY"))}

# ----------------------------
# Core: script generation (TTS 규칙 포함)
# ----------------------------
def generate_script(script_type: str) -> str:
    news = fetch_news(limit=25)
    if not news:
        return "뉴스를 가져오지 못했습니다. RSS 소스를 확인해 주세요."

    # 입력을 줄여 비용 최소화 (제목+링크 정도)
    candidates = "\n".join(
        [f"- {n['title']} ({n['source']})\n  link: {n['link']}" for n in news[:10]]
    )

    # ✅ 프롬프트에 TTS 규칙 추가
    tts_rules = """
[TTS 음성 최적화 규칙]
- 특수문자 사용 금지: #, *, _, ~, >, <, {}, [], =, +, ^, |, \\
- 이모지 사용 금지
- 불필요한 따옴표(" ') 금지
- 슬래시(/) 금지 -> 대신 "또는" 사용
- 괄호 최소화, 메타 지시문 금지(예: 효과음, 장면, 강조 표시)
- 숫자/단위: %는 '퍼센트', $는 '달러', ₩는 '원'으로 표기
- 영어 약어는 가능한 한 풀어서(예: CPI -> 소비자물가지수)

[문장 규칙]
- 한 문장은 짧게(대략 15~20단어 이내 느낌)
- 쉼표보다 마침표를 많이 사용
- 아나운서가 읽기 자연스럽게, 말하듯이
- 출력은 오직 '읽기용 대본'만. 제목/설명/주석/목차 금지.
"""

    if script_type == "short":
        instruction = f"""
너는 경제 유튜브 쇼츠 대본 작가다.
아래 뉴스 후보 중 오늘 조회수 잘 나올 1개를 골라 45~60초 한국어 대본을 써라.

구성:
- 첫 문장: 훅(숫자/놀라운 변화/내 돈에 영향)
- 본문: 핵심 3~5문장(왜 중요한지, 시장/생활 영향, 투자자 관점 1문장)
- 마지막: CTA 1문장(구독/댓글 유도)
- 과장 금지. 단정 대신 가능성/전망 표현.
- 마지막 줄에 출처 링크 1개를 '출처: 링크' 형식으로만 표기.

{tts_rules}

[뉴스 후보]
{candidates}
"""
    else:
        instruction = f"""
너는 경제 유튜브 롱폼 대본 작가다.
아래 뉴스 후보 중 2개를 골라 5~8분 분량 한국어 대본을 써라.

구성:
1) 오프닝 훅(15초)
2) 뉴스1 깊게(배경, 핵심 포인트, 시나리오 2개, 수혜/피해 섹터)
3) 뉴스2 빠르게(핵심만)
4) 오늘의 체크리스트(시청자가 볼 지표 3개)
5) 마무리 CTA

마지막에 출처 링크 2개를 '출처: 링크1, 링크2' 형식으로만 표기.

{tts_rules}

[뉴스 후보]
{candidates}
"""

    r = client.responses.create(
        model=MODEL,
        input=[{"role": "user", "content": instruction}],
    )
    script = r.output_text.strip()

    # ✅ 후처리로 한 번 더 안전하게 정리(TTS 깨짐 방지)
    script = tts_clean(script)
    return script

@app.post("/api/script")
def api_script(req: ScriptReq):
    if req.type not in ("short", "long"):
        raise HTTPException(400, "type must be 'short' or 'long'")
    script = generate_script(req.type)
    return {"script": script, "download_url": ""}

# ----------------------------
# Video rendering (MVP)
# - TTS: edge-tts(무료 계열) 사용 예시
# - Video: ffmpeg로 단색 배경 + 자막(간단) + 음성 합성
# ----------------------------
def run_edge_tts(text: str, out_mp3: str, voice: str = "ko-KR-SunHiNeural", rate: str = "+0%"):
    """
    edge-tts CLI를 사용(간편).
    Cloud Run 컨테이너에 edge-tts 설치 필요.
    """
    # 텍스트가 너무 길면 TTS가 실패할 수 있어 MVP는 길이 제한 추천
    text = text.strip()
    if not text:
        raise RuntimeError("TTS text empty")

    cmd = [
        "edge-tts",
        "--voice", voice,
        "--rate", rate,
        "--text", text,
        "--write-media", out_mp3,
    ]
    p = subprocess.run(cmd, capture_output=True, text=True)
    if p.returncode != 0:
        raise RuntimeError(f"edge-tts failed: {p.stderr[:3000]}")

def make_srt_from_sentences(sentences: list[str], total_sec: float) -> str:
    """
    아주 단순: 문장 수로 균등 분배.
    (나중에 실제 TTS 단어 타이밍 기반으로 개선 가능)
    """
    if not sentences:
        sentences = [""]

    per = max(1.0, total_sec / len(sentences))
    lines = []
    t = 0.0

    def fmt(ts: float) -> str:
        h = int(ts // 3600)
        m = int((ts % 3600) // 60)
        s = int(ts % 60)
        ms = int((ts - int(ts)) * 1000)
        return f"{h:02d}:{m:02d}:{s:02d},{ms:03d}"

    for i, sent in enumerate(sentences, start=1):
        start = t
        end = min(total_sec, t + per)
        t = end
        lines.append(str(i))
        lines.append(f"{fmt(start)} --> {fmt(end)}")
        lines.append(sent)
        lines.append("")
    return "\n".join(lines)

def ffprobe_duration(path: str) -> float:
    cmd = ["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "default=noprint_wrappers=1:nokey=1", path]
    p = subprocess.run(cmd, capture_output=True, text=True)
    if p.returncode != 0:
        raise RuntimeError(f"ffprobe failed: {p.stderr[:2000]}")
    return float(p.stdout.strip())

def render_video_job(job_id: str, kind: str):
    """
    백그라운드 작업: script -> TTS(mp3) -> srt -> ffmpeg(mp4)
    """
    try:
        with JOBS_LOCK:
            JOBS[job_id]["status"] = "running"
            JOBS[job_id]["message"] = "대본 생성 중..."

        script = generate_script(kind)

        # 짧게 제한(쇼츠 기준). 롱폼은 나중에 '씬 분할' 필요.
        if kind == "short":
            tts_text = script
        else:
            # 롱폼은 MVP로 앞부분만(너무 길면 TTS/ffmpeg 시간이 커짐)
            tts_text = " ".join(split_sentences_kor(script)[:30])

        tts_text = tts_clean(tts_text)

        with JOBS_LOCK:
            JOBS[job_id]["message"] = "TTS 생성 중..."

        mp3_path = os.path.join(TMP_DIR, f"{job_id}.mp3")
        run_edge_tts(tts_text, mp3_path)

        dur = ffprobe_duration(mp3_path)

        with JOBS_LOCK:
            JOBS[job_id]["message"] = "자막 생성 중..."

        sentences = split_sentences_kor(tts_text)
        srt_path = os.path.join(TMP_DIR, f"{job_id}.srt")
        with open(srt_path, "w", encoding="utf-8") as f:
            f.write(make_srt_from_sentences(sentences, dur))

        with JOBS_LOCK:
            JOBS[job_id]["message"] = "영상 렌더링 중..."

        mp4_path = os.path.join(TMP_DIR, f"{job_id}.mp4")

        # 단색 배경 + 자막 + 오디오 합성
        # 폰트 문제 피하려면 컨테이너에 폰트 패키지 설치 필요 (아래 안내 참고)
        cmd = [
            "ffmpeg", "-y",
            "-f", "lavfi", "-i", f"color=c=black:s=1080x1920:r=30:d={dur}",
            "-i", mp3_path,
            "-vf", f"subtitles={srt_path}",
            "-c:v", "libx264", "-pix_fmt", "yuv420p",
            "-c:a", "aac", "-b:a", "192k",
            "-shortest",
            mp4_path
        ]
        p = subprocess.run(cmd, capture_output=True, text=True)
        if p.returncode != 0:
            raise RuntimeError(f"ffmpeg failed: {p.stderr[-3000:]}")

        with JOBS_LOCK:
            JOBS[job_id]["status"] = "done"
            JOBS[job_id]["message"] = "완료"
            JOBS[job_id]["video_path"] = mp4_path
            JOBS[job_id]["script"] = script

    except Exception as e:
        with JOBS_LOCK:
            JOBS[job_id]["status"] = "error"
            JOBS[job_id]["message"] = str(e)

@app.post("/api/render")
def api_render(req: RenderReq):
    if req.type not in ("short", "long"):
        raise HTTPException(400, "type must be 'short' or 'long'")

    job_id = str(uuid.uuid4())
    with JOBS_LOCK:
        JOBS[job_id] = {"status": "queued", "message": "대기 중", "video_path": None, "script": ""}

    th = threading.Thread(target=render_video_job, args=(job_id, req.type), daemon=True)
    th.start()

    return {"job_id": job_id}

@app.get("/api/render/status")
def api_render_status(job_id: str):
    with JOBS_LOCK:
        job = JOBS.get(job_id)
    if not job:
        raise HTTPException(404, "job not found")

    if job["status"] == "done":
        return {
            "status": "done",
            "message": job["message"],
            "video_url": f"/download/video/{job_id}",
            "script": job.get("script", "")
        }
    if job["status"] == "error":
        return {"status": "error", "message": job["message"]}
    return {"status": job["status"], "message": job["message"]}

@app.get("/download/video/{job_id}")
def download_video(job_id: str):
    with JOBS_LOCK:
        job = JOBS.get(job_id)
    if not job or job.get("status") != "done" or not job.get("video_path"):
        raise HTTPException(404, "video not ready")
    return FileResponse(job["video_path"], media_type="video/mp4", filename=f"{job_id}.mp4")
