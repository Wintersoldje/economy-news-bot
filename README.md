# MVP: Static Frontend + FastAPI Backend

## 구조
- `/site`: 정적 웹사이트(HTML/CSS/JS). GitHub Pages 호스팅 가능.
- `/backend`: FastAPI 백엔드. Cloud Run 배포 가능한 형태(컨테이너화 전제).

---

## 백엔드 로컬 실행
```bash
pip install -r backend/requirements.txt
uvicorn backend.app:app --reload --port 8000
```
- 기본 URL: `http://localhost:8000`

## 프론트 로컬 실행(간단)
```bash
cd site
python -m http.server 5500
```
- 접속: `http://localhost:5500`

---

## API
- `POST /api/script`  body: `{ "type": "short" | "long" }`
  - 응답: `{ script, download_url }`
- `POST /api/render`  body: `{ "type": "short" | "long" }`
  - 응답: `{ job_id }`
- `GET /api/render/status?job_id=...`
  - 응답(진행중): `{ status: "queued"|"running" }`
  - 응답(완료): `{ status: "done", video_url }`

---

## 메모
- 파일 저장은 MVP로 로컬 `/tmp` 사용.
  - 추후 GCS로 교체 가능하도록 백엔드 코드에 주석 포함.
- `POST /api/render`는 `ffmpeg`가 설치되어 있으면 더미 MP4를 생성합니다.
  - `ffmpeg`가 없으면 실패 상태가 반환됩니다.
