const time = document.querySelector("#time");
const progress = document.querySelector("#progress");
const phase = document.querySelector("#phase");
const detail = document.querySelector("#detail");
const progressCount = document.querySelector("#progress-count");
const colors = { rest: "#56d6a0", prep: "#9b8cff", work: "#22c7ff" };
const requestedAccent = new URLSearchParams(location.search).get("accent");
let accent = /^#[0-9a-f]{6}$/i.test(requestedAccent || "") ? requestedAccent : null;

function render(state) {
  if (time) time.textContent = state.time || "00:00";
  if (progress) {
    progress.style.width = `${Math.round((state.progress || 0) * 100)}%`;
    progress.style.background = accent || colors[state.phase_role] || "#22c7ff";
  }
  if (phase) phase.textContent = `${state.phase_name || "Готов к началу"}${state.phase === 'paused' ? ' · пауза' : ''}`;
  if (detail) detail.textContent = state.next_phase_name ? `Далее: ${state.next_phase_name}` : state.scenario_name ? `Сценарий: ${state.scenario_name}` : "WorkTimer";
  if (progressCount) progressCount.textContent = state.progress_total ? `${state.progress_current || 0} / ${state.progress_total}` : "Без лимита";
}

fetch("/api/preferences").then(response => response.json()).then(preferences => {
  if (!accent && /^#[0-9a-f]{6}$/i.test(preferences.overlay_accent || "")) accent = preferences.overlay_accent;
}).catch(() => {});
let lastEvent = 0;
async function refresh() { try { const response=await fetch("/api/state"); if(response.ok)render(await response.json()); } catch {} }
refresh(); const stream = new EventSource("/api/events"); stream.addEventListener("state", event => { lastEvent=Date.now(); render(JSON.parse(event.data)); });
setInterval(() => { if(Date.now()-lastEvent>2500)refresh(); },3000);
