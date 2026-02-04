from __future__ import annotations
import time
from typing import List, Dict
import feedparser

# 무료 RSS(한국) — 우선 이 2개로 시작
RSS_FEEDS = [
    "https://www.yonhapnewseconomytv.com/rss/allArticle.xml",  # 연합뉴스경제TV 전체기사 :contentReference[oaicite:2]{index=2}
    "http://www.yonhaptv.co.kr/rss/S1N2.xml",                  # 연합뉴스TV 경제 :contentReference[oaicite:3]{index=3}
]

_cache = {"ts": 0, "items": []}
CACHE_TTL_SEC = 300  # 5분 캐시 (비용/속도 최적화)

def fetch_news(limit: int = 8) -> List[Dict]:
    now = time.time()
    if _cache["items"] and now - _cache["ts"] < CACHE_TTL_SEC:
        return _cache["items"][:limit]

    items: List[Dict] = []
    for url in RSS_FEEDS:
        feed = feedparser.parse(url)
        for e in feed.entries[:limit]:
            items.append({
                "source": getattr(feed.feed, "title", "RSS"),
                "title": getattr(e, "title", "").strip(),
                "link": getattr(e, "link", "").strip(),
                "summary": (getattr(e, "summary", "") or "").strip(),
                "published": getattr(e, "published", "") or getattr(e, "updated", ""),
            })

    # 제목 기준 중복 제거
    seen = set()
    uniq = []
    for it in items:
        key = it["title"]
        if key and key not in seen:
            seen.add(key)
            uniq.append(it)

    _cache["ts"] = now
    _cache["items"] = uniq
    return uniq[:limit]
