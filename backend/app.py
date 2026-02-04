import os
from fastapi import FastAPI
from pydantic import BaseModel
from fastapi.middleware.cors import CORSMiddleware

from openai import OpenAI
from .news import fetch_news

app = FastAPI()

app.add_middleware(
    CORSMiddleware,
    allow_origins=["https://wintersoldje.github.io"],
    allow_methods=["*"],
    allow_headers=["*"],
)

client = OpenAI()
MODEL = os.getenv("OPENAI_MODEL", "gpt-4o-mini")  # 비용 최소 기본값

class ScriptReq(BaseModel):
    type: str  # "short" | "long"

@app.get("/health")
def health():
    return {"ok": True}

@app.post("/api/script")
def make_script(req: ScriptReq):
    news = fetch_news(limit=8)

    # 뉴스가 없을 때도 실패하지 않게
    if not news:
        return {"script": "뉴스를 가져오지 못했습니다. RSS 소스를 확인하세요.", "download_url": ""}

    # LLM 입력(짧게 유지 = 비용 절감)
    bullets = "\n".join([f"- {n['title']} ({n['source']})\n  link: {n['link']}" for n in news[:6]])

    if req.type == "short":
        instruction = """
너는 경제 유튜브 쇼츠 대본 작가다.
아래 뉴스 5~6개 중 오늘 '가장 터질만한' 1개를 골라 45~60초짜리 한국어 쇼츠 대본을 써라.
규칙:
- 첫 문장: 훅(강한 문제제기/숫자/놀라운 포인트)
- 본문: 핵심 3줄(왜 중요한지, 시장/생활 영향, 투자자 관점 1줄)
- 마지막: CTA(구독/댓글 유도) 1줄
- 과장 금지, 단정 대신 '가능성/전망' 표현
- 마지막 줄에 [출처]로 선택한 기사 링크 1개만 포함
"""
    else:
        instruction = """
너는 경제 유튜브 롱폼 대본 작가다.
아래 뉴스 5~6개 중 2개를 골라 5~8분 분량 한국어 대본을 써라.
구성:
1) 오프닝 훅 15초
2) 뉴스1 깊게(배경, 핵심 숫자/키워드, 시나리오 2개, 수혜/피해 섹터)
3) 뉴스2 빠르게(핵심만)
4) 오늘의 체크리스트(시청자가 볼 지표 3개)
5) 마무리 CTA
마지막에 [출처]로 기사 링크 2개를 나열
"""

    prompt = f"{instruction}\n\n[오늘 뉴스 후보]\n{bullets}"

    r = client.responses.create(
        model=MODEL,
        input=[{"role": "user", "content": prompt}],
    )
    script = r.output_text.strip()

    return {"script": script, "download_url": ""}  # 다운로드는 다음 단계에서 붙이자(지금은 비용/복잡도 ↓)
