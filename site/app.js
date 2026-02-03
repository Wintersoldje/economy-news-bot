/*
  API_BASE: later replace with Cloud Run URL, e.g.
  const API_BASE = "https://your-service-xxxxx-uc.a.run.app";
*/
const API_BASE = "http://localhost:8000";

const $ = (id) => document.getElementById(id);

const scriptOutput = $("script-output");
const scriptDownload = $("script-download");

const renderStatus = $("render-status");
const videoDownload = $("video-download");

const btnScriptShort = $("btn-script-short");
const btnScriptLong = $("btn-script-long");
const btnRenderShort = $("btn-render-short");
const btnRenderLong = $("btn-render-long");

let pollTimer = null;

function setBusy(isBusy) {
  [btnScriptShort, btnScriptLong, btnRenderShort, btnRenderLong].forEach((b) => (b.disabled = isBusy));
}

function absoluteUrl(pathOrUrl) {
  // Backend returns relative URLs like /api/download/script/...
  if (!pathOrUrl) return "";
  if (/^https?:\/\//i.test(pathOrUrl)) return pathOrUrl;
  return API_BASE.replace(/\/$/, "") + pathOrUrl;
}

async function postJson(path, body) {
  const res = await fetch(API_BASE + path, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });

  const text = await res.text();
  let data;
  try {
    data = text ? JSON.parse(text) : {};
  } catch {
    data = { raw: text };
  }

  if (!res.ok) {
    const msg = data?.detail || data?.error || res.statusText;
    throw new Error(msg);
  }

  return data;
}

async function getJson(path) {
  const res = await fetch(API_BASE + path);
  const text = await res.text();
  let data;
  try {
    data = text ? JSON.parse(text) : {};
  } catch {
    data = { raw: text };
  }
  if (!res.ok) {
    const msg = data?.detail || data?.error || res.statusText;
    throw new Error(msg);
  }
  return data;
}

function stopPolling() {
  if (pollTimer) {
    clearInterval(pollTimer);
    pollTimer = null;
  }
}

async function handleScript(type) {
  stopPolling();
  setBusy(true);
  scriptOutput.textContent = "불러오는 중...";
  scriptDownload.style.display = "none";
  scriptDownload.href = "#";

  try {
    const data = await postJson("/api/script", { type });
    scriptOutput.textContent = data.script || "";

    const url = absoluteUrl(data.download_url);
    if (url) {
      scriptDownload.href = url;
      scriptDownload.download = type + "_script.txt";
      scriptDownload.style.display = "inline-block";
    }
  } catch (e) {
    scriptOutput.textContent = "에러: " + (e?.message || String(e));
  } finally {
    setBusy(false);
  }
}

async function handleRender(type) {
  stopPolling();
  setBusy(true);
  renderStatus.textContent = "렌더 작업 시작 중...";
  videoDownload.style.display = "none";
  videoDownload.href = "#";

  try {
    const data = await postJson("/api/render", { type });
    const jobId = data.job_id;
    if (!jobId) throw new Error("job_id가 없습니다.");

    renderStatus.textContent = `job_id: ${jobId} (상태 확인 중...)`;

    pollTimer = setInterval(async () => {
      try {
        const status = await getJson(`/api/render/status?job_id=${encodeURIComponent(jobId)}`);
        if (status.status === "done") {
          stopPolling();
          renderStatus.textContent = `완료: ${jobId}`;
          const url = absoluteUrl(status.video_url);
          if (url) {
            videoDownload.href = url;
            videoDownload.download = type + "_video.mp4";
            videoDownload.style.display = "inline-block";
          }
          setBusy(false);
        } else if (status.status === "failed") {
          stopPolling();
          renderStatus.textContent = `실패: ${status.error || "unknown error"}`;
          setBusy(false);
        } else {
          renderStatus.textContent = `진행중 (${status.status}): ${jobId}`;
        }
      } catch (e) {
        stopPolling();
        renderStatus.textContent = "상태 조회 에러: " + (e?.message || String(e));
        setBusy(false);
      }
    }, 1000);
  } catch (e) {
    renderStatus.textContent = "에러: " + (e?.message || String(e));
    setBusy(false);
  }
}

btnScriptShort.addEventListener("click", () => handleScript("short"));
btnScriptLong.addEventListener("click", () => handleScript("long"));
btnRenderShort.addEventListener("click", () => handleRender("short"));
btnRenderLong.addEventListener("click", () => handleRender("long"));
