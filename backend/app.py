import os
import re
import subprocess
from fastapi import FastAPI, HTTPException, Body
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from openai import OpenAI
from news import fetch_news  # backend/news.py

app = FastAPI()

app.add_middleware(
    CORSMiddleware,
    allow_origins=["https://wintersoldje.github.io"],
    allow_methods=["*"],
    allow_headers=["*"],
)

client = OpenAI()
MODEL = os.getenv("OPENAI_MODEL", "gpt-4o-mini")

TMP_DIR = "/tmp/econbot"
os.makedirs(TMP_DIR, exist_ok=True)

# ----------------------------
# TTS-safe cleaning
# ----------------------------
_EMOJI_RE = re.compile(
    "[" "\U0001F600-\U0001F64F" "\U0001F300-\U0001F5FF" "\U0001F680-\U0001F6FF"
    "\U0001F1E0-\U0001F1FF" "\U00002700-\U000027BF" "\U0001F900-\U0001F9FF"
    "\U00002600-\U000026FF" "]+",
    flags=re.UNICODE,
)

def tts_clean(text: str) -> str:
    if not text:
        return ""
    text = _EMOJI_RE.sub("", text)
    text = re.sub(r"[#*_~><{}\[\]=+\^|\\]", " ", text)
    text = text.replace("/", " 또는 ")
    text = text.replace('"', "").replace("'", "").replace("`", "")
    text = text.replace("%", " 퍼센트 ").replace("$", " 달러 ").replace("₩", " 원 ")
    text = re.sub(r"(\d),(\d)", r"\1\2", text)  # 1,000 -> 1000
    text = re.sub(r"\s+", " ", text).strip()
    return text

def split_sentences_kor(text: str) -> list[str]:
    # 아주 단순 분리 (MVP)
    text = text.replace("다.", "다.\n").replace("요.", "요.\n")
    parts = [p.strip() for p in text.split("\n") if p.strip()]
    return parts

def make_srt(sentences: list[str], total_sec: float) -> str:
    if not sentences:
        sentences = [""]

    per = max(1.0, total_sec / len(sentences))
    t = 0.0
    out = []

    def fmt(ts: float) -> str:
        h = int(ts // 3600)
        m = int((ts % 3600) // 60)
        s = int(ts % 60)
        ms = int((ts - int(ts)) * 1000)
        return f"{h:02d}:{m:02d}:{s:02d},{ms:03d}"

    for i, s in enumerate(sentences, start=1):
        start = t
        end = min(total_sec, t + per)
        t = end
        out.append(str(i))
        out.append(f"{fmt(start)} --> {fmt(end)}")
        out.append(s)
        out.append("")
    return "\n".join(out)

def ffprobe_duration(path: str) -> float:
    cmd = [
        "ffprobe", "-v", "error", "-show_entries", "format=duration",
        "-of", "default=noprint_wrappers=1:nokey=1", path
    ]
    p = subprocess.run(cmd, capture_output=True, text=True)
    if p.returncode != 0:
        raise RuntimeError(p.stderr[-2000:])
    return float(p.stdout.strip())

def run_edge_tts(text: str, out_mp3: str, voice: str = "ko-KR-SunHiNeural", rate: str = "+0%"):
    cmd = [
        "edge-tts",
        "--voice", voice,
        "--rate", rate,
        "--text", text,
        "--write-media", out_mp3,
    ]
    p = subprocess.run(cmd, capture_output=True, text=True)
    if p.returncode != 0:
        raise RuntimeError(p.stderr[-3000:])

def generate_script(kind: str) -> str:
    news = fetch_news(limit=25)
    if not news:
        return "뉴스를 가져오지 못했습니다. RSS 소스를 확인해 주세요."

    candidates = "\n".join([f"- {n['title']} ({n['source']})\n  link: {n['link']}" for n in news[:10]])

    tts_rules = """
[TTS 음성 최적화 규칙]
- 특수문자 금지: #, *, _, ~, >, <, {}, [], =, +, ^, |, \\
- 이모지 금지
- 따옴표 금지
- 슬래시 금지 -> 대신 '또는'
- 괄호 최소화, 메타 지시문 금지(효과음/장면/강조)
- %는 퍼센트, $는 달러, ₩는 원
- 영어 약어는 풀어서(예: CPI -> 소비자물가지수)
- 출력은 읽기용 대본만. 제목/설명/주석 금지.
"""

    if kind == "short":
        prompt = f"""
너는 경제 유튜브 쇼츠 대본 작가다.
아래 뉴스 후보 중 오늘 조회수 잘 나올 1개를 골라 45~60초 한국어 대본을 써라.

구성:
- 첫 문장: 훅(숫자/놀라운 변화/내 돈 영향)
- 본문: 4~6문장(왜 중요한지, 생활/시장 영향, 투자자 관점 1문장)
- 마지막: CTA 1문장

{tts_rules}

[뉴스 후보]
{candidates}
"""
    else:
        prompt = f"""
너는 경제 유튜브 롱폼 대본 작가다.
아래 뉴스 후보 중 2개를 골라 5~8분 한국어 대본을 써라.

구성:
- 오프닝 훅
- 뉴스1 깊게(배경/핵심/시나리오2/수혜피해)
- 뉴스2 빠르게
- 체크리스트 3개
- 마무리 CTA

{tts_rules}

[뉴스 후보]
{candidates}
"""

    r = client.responses.create(model=MODEL, input=[{"role": "user", "content": prompt}])
    return tts_clean(r.output_text.strip())

@app.get("/health")
def health():
    return {"ok": True}

@app.post("/api/render")
def render_video(payload=Body(...)):
    """
    동기 렌더:
    - 요청이 오면 대본 생성 -> TTS(mp3) -> srt -> ffmpeg(mp4)
    - mp4를 바로 반환
    """
    kind = (payload.get("type") or "").strip()
    if kind not in ("short", "long"):
        raise HTTPException(400, "type must be 'short' or 'long'")

    # 1) 스크립트 생성
    script = generate_script(kind)

    # 롱폼은 MVP로 앞부분만(너무 길면 TTS/렌더 오래 걸림)
    tts_text = script
    if kind == "long":
        tts_text = " ".join(split_sentences_kor(script)[:40])
        tts_text = tts_clean(tts_text)

    # 2) TTS
    base = os.path.join(TMP_DIR, f"render_{os.getpid()}")
    mp3_path = base + ".mp3"
    srt_path = base + ".srt"
    mp4_path = base + ".mp4"

    run_edge_tts(tts_text, mp3_path)

    # 3) 자막
    dur = ffprobe_duration(mp3_path)
    sentences = split_sentences_kor(tts_text)
    with open(srt_path, "w", encoding="utf-8") as f:
        f.write(make_srt(sentences, dur))

    # 4) 영상 (단색 배경 + 자막 + 오디오)
    cmd = [
        "ffmpeg", "-y",
        "-f", "lavfi", "-i", f"color=c=black:s=1080x1920:r=30:d={dur}",
        "-i", mp3_path,
        "-vf", f"subtitles={srt_path}:force_style='FontName=/usr/share/fonts/truetype/noto/NotoSansCJK-Regular.ttc,FontSize=64,Outline=2,Shadow=1'",
        "-c:v", "libx264", "-pix_fmt", "yuv420p",
        "-c:a", "aac", "-b:a", "192k",
        "-shortest",
        mp4_path
    ]
    p = subprocess.run(cmd, capture_output=True, text=True)
    if p.returncode != 0:
        raise HTTPException(500, f"ffmpeg failed: {p.stderr[-1500:]}")

    # mp4 바로 내려주기
    return FileResponse(mp4_path, media_type="video/mp4", filename=f"{kind}.mp4")
