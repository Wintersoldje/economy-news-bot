// ✅ 여기만 나중에 Cloud Run URL로 바꾸면 됨 (https://... 형태)
// 예: const API_BASE = "https://your-cloud-run-url";
const API_BASE = "https://economy-news-bot-924911799522.asia-northeast3.run.app"; // 지금은 빈 값이면 "데모 모드"로 동작하게 해둠

const $ = (id) => document.getElementById(id);

function setStatus(msg) {
  $("status").textContent = msg;
}

function setOutput(text) {
  $("output").value = text;
}

function setDownload(url, label) {
  const a = $("downloadLink");
  if (!url) {
    a.textContent = "(아직 없음)";
    a.href = "#";
    a.style.pointerEvents = "none";
    a.style.opacity = "0.5";
    return;
  }
  a.textContent = label || "다운로드";
  a.href = url;
  a.style.pointerEvents = "auto";
  a.style.opacity = "1";
}

function logDemo(action) {
  const now = new Date().toLocaleString();
  setStatus(`✅ 클릭 감지됨: ${action}`);
  setOutput(`[${now}] "${action}" 버튼이 눌렸습니다.\n\n- 지금은 API_BASE가 비어 있어서 데모 모드입니다.\n- 백엔드 URL(Cloud Run)을 만들면 API_BASE에 넣고 실제 호출로 전환됩니다.\n`);
  setDownload("", "");
}

async function apiPost(path, body) {
  if (!API_BASE) throw new Error("API_BASE가 비어있습니다. (백엔드 URL 필요)");
  const res = await fetch(API_BASE + path, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body || {}),
  });
  if (!res.ok) {
    const t = await res.text();
    throw new Error(`HTTP ${res.status}: ${t}`);
  }
  return res.json();
}

async function apiGet(path) {
  if (!API_BASE) throw new Error("API_BASE가 비어있습니다. (백엔드 URL 필요)");
  const res = await fetch(API_BASE + path);
  if (!res.ok) {
    const t = await res.text();
    throw new Error(`HTTP ${res.status}: ${t}`);
  }
  return res.json();
}

async function handleScript(type) {
  try {
    setStatus("요청 중...");
    setDownload("", "");
    const data = await apiPost("/api/script", { type });
    setStatus("완료");
    setOutput(data.script || JSON.stringify(data, null, 2));
    setDownload(data.download_url || "", "대본 다운로드");
  } catch (e) {
    // 데모 모드라도 “클릭은 됐는지” 보이게
    logDemo(`${type.toUpperCase()} 대본 보기`);
    setOutput((e && e.message ? e.message : String(e)) + "\n\n" + $("output").value);
  }
}

async function handleRender(type) {
  try {
    setStatus("렌더 요청...");
    setDownload("", "");
    setOutput("");

    if (!API_BASE) throw new Error("API_BASE가 비어있습니다. Cloud Run URL을 넣어주세요.");

    const res = await fetch(API_BASE + "/api/render", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ type }),
    });

    if (!res.ok) {
      const t = await res.text();
      throw new Error(`HTTP ${res.status}: ${t}`);
    }

    const blob = await res.blob();
    const url = URL.createObjectURL(blob);

    setStatus("완료");
    setOutput("영상이 생성되었습니다. 아래 다운로드 링크를 누르세요.");
    setDownload(url, "영상 다운로드");
  } catch (e) {
    setStatus("❌ 오류");
    setOutput(e?.message || String(e));
    setDownload("", "");
  }
}


function bind() {
  const shortS = $("btnShortScript");
  const longS = $("btnLongScript");
  const shortV = $("btnShortVideo");
  const longV = $("btnLongVideo");

  // ✅ 버튼 요소를 못 찾으면 여기서 바로 표시됨
  if (!shortS || !longS || !shortV || !longV) {
    setStatus("❌ 버튼 요소를 찾지 못함 (id 불일치)");
    setOutput("index.html의 버튼 id와 app.js의 id가 일치하는지 확인하세요.");
    return;
  }

  shortS.addEventListener("click", () => handleScript("short"));
  longS.addEventListener("click", () => handleScript("long"));
  shortV.addEventListener("click", () => handleRender("short"));
  longV.addEventListener("click", () => handleRender("long"));

  setStatus("✅ 준비 완료 (JS 연결됨)");
  setOutput("버튼을 눌러보세요. (데모 모드에서도 클릭 로그가 떠야 정상)");
}

document.addEventListener("DOMContentLoaded", bind);
