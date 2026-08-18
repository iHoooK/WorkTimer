const $ = (selector, root = document) => root.querySelector(selector);
const $$ = (selector, root = document) => [...root.querySelectorAll(selector)];
const formatDuration = seconds => `${Math.floor(seconds / 60)}:${String(seconds % 60).padStart(2, "0")}`;
let scenariosCache = [];
let editingScenarioId = null;

function activateView(view) {
  $$(".nav-item").forEach(button => button.classList.toggle("is-active", button.dataset.view === view));
  $$(".view").forEach(panel => panel.classList.toggle("is-visible", panel.dataset.panel === view));
  $("#view-kicker").textContent = view === "now" ? "Текущая сессия" : view;
}

function renderScenarios(items) {
  const list = $("#scenario-list");
  list.replaceChildren();
  for (const scenario of items) {
    const row = document.createElement("article"); row.className = "scenario-row";
    const content = document.createElement("div");
    const title = document.createElement("h2"); title.textContent = scenario.name;
    const details = document.createElement("p"); details.textContent = scenario.phases.map(phase => `${phase.name} · ${formatDuration(phase.duration_seconds)}`).join("  /  ");
    const button = document.createElement("button"); button.className = "text-button"; button.type = "button"; button.dataset.select = scenario.id; button.textContent = "Выбрать";
    content.append(title, details); row.append(content, button); list.append(row);
  }
}

function renderCurrentScenario(items, scenarioId) {
  const scenario = items.find(item => item.id === scenarioId) || items[0];
  if (!scenario) return;
  $("#scenario-heading").textContent = scenario.name;
  const phaseList = $("#phase-list"); phaseList.replaceChildren();
  scenario.phases.forEach((phase, index) => {
    const row = document.createElement("li"); if (index === 0) row.className = "current";
    const number = document.createElement("b"); number.textContent = String(index + 1);
    const name = document.createElement("span"); name.textContent = phase.name;
    const duration = document.createElement("time"); duration.textContent = formatDuration(phase.duration_seconds);
    const start = document.createElement("button"); start.className = "text-button"; start.type = "button"; start.dataset.phaseStart = phase.position; start.textContent = "Запустить";
    row.append(number, name, duration, start); phaseList.append(row);
  });
}

function applyState(state) {
  $("#timer-value").textContent = state.time || "00:00";
  $("#phase-name").textContent = state.phase_name || "Готов к началу";
  $("#progress-value").style.width = `${Math.round((state.progress || 0) * 100)}%`;
  $("#toggle-timer").textContent = state.phase === "running" ? "Пауза" : state.phase === "paused" ? "Продолжить" : "Начать";
}

async function load() {
  try {
    const [state, scenarios, preferences] = await Promise.all([fetch("/api/state").then(r => r.json()), fetch("/api/scenarios").then(r => r.json()), fetch("/api/preferences").then(r => r.json())]);
    applyState(state);
    renderScenarios(scenarios.items);
    scenariosCache = scenarios.items.filter(item => !item.is_archived);
    if (editingScenarioId === null && scenariosCache.length) editingScenarioId = state.scenario_id || scenariosCache[0].id;
    renderEditor(scenariosCache.find(item => item.id === editingScenarioId) || null);
    loadTasks(state);
    loadHistory();
    renderCurrentScenario(scenarios.items, state.scenario_id);
    $("#pref-sound").checked = Boolean(preferences.sound_enabled);
    $("#pref-dnd").checked = Boolean(preferences.dnd);
    $("#pref-warning").value = String(preferences.warning_seconds ?? 60);
    $("#pref-pomodoro-work").value = String(preferences.pomodoro_work_minutes ?? 25);
    $("#pref-pomodoro-break").value = String(preferences.pomodoro_break_minutes ?? 5);
    $("#pref-auto-start").checked = Boolean(preferences.auto_start_next_phase);
    $("#pref-overlay-accent").value = preferences.overlay_accent || "#22c7ff";
    ["#toggle-timer", "#next-phase", "#repeat-phase", "#restart-scenario"].forEach(selector => { $(selector).disabled = !scenarios.items.length; });
    $("#connection-label").textContent = "локальная панель";
    $(".connection i").style.background = "var(--rest)";
  } catch { $("#connection-label").textContent = "нет соединения"; }
}

async function postAction(url) {
  const response = await fetch(url, { method: "POST" });
  if (!response.ok) throw new Error("Не удалось выполнить действие");
  const state = await response.json(); applyState(state); return state;
}

$$("[data-view]").forEach(button => button.addEventListener("click", () => activateView(button.dataset.view)));
load();
$("#toggle-timer").addEventListener("click", () => postAction("/api/timer/toggle").catch(load));
$("#next-phase").addEventListener("click", () => postAction("/api/timer/next").catch(load));
$("#repeat-phase").addEventListener("click", () => postAction("/api/timer/repeat").catch(load));
$("#restart-scenario").addEventListener("click", () => postAction("/api/timer/restart").catch(load));
$("#free-timer").addEventListener("click", () => postAction("/api/timer/free").catch(load));
$("#pomodoro-timer").addEventListener("click", async () => {
  const preferences = await fetch("/api/preferences").then(response => response.json());
  const response = await fetch("/api/timer/pomodoro", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      work_seconds: Number(preferences.pomodoro_work_minutes ?? 25) * 60,
      break_seconds: Number(preferences.pomodoro_break_minutes ?? 5) * 60,
      long_break_seconds: Number(preferences.pomodoro_long_break_minutes ?? 15) * 60,
      cycles_before_long_break: Number(preferences.pomodoro_cycles_before_long_break ?? 4),
    }),
  });
  if (response.ok) applyState(await response.json()); else load();
});
$("#scenario-list").addEventListener("click", event => { const button = event.target.closest("[data-select]"); if (button) { editingScenarioId = Number(button.dataset.select); postAction(`/api/scenarios/${button.dataset.select}/select`).then(load).catch(load); } });
$("#phase-list").addEventListener("click", event => { const button = event.target.closest("[data-phase-start]"); if (button) postAction(`/api/timer/phase/${button.dataset.phaseStart}`).catch(load); });
const events = new EventSource("/api/events");
events.addEventListener("state", event => applyState(JSON.parse(event.data)));
events.onerror = () => setTimeout(load, 1000);

function renderTasks(tasks, groups, state, summary) {
  const groupSelect = $("#task-group"), parentSelect = $("#group-parent");
  [groupSelect, parentSelect].forEach(select => { const previous = select.value; while (select.options.length > 1) select.remove(1); groups.forEach(group => { const option = document.createElement("option"); option.value = group.id; option.textContent = `${group.parent_id ? "↳ " : ""}${group.name}`; select.append(option); }); select.value = previous; });
  const totals = new Map(summary.map(item => [item.task_id, item.elapsed_seconds])); const list = $("#task-list"); list.replaceChildren();
  tasks.forEach(task => { const row = document.createElement("article"); row.className = `task-row${task.id === state.active_task_id ? " is-active" : ""}`; const content = document.createElement("div"); const title = document.createElement("h2"); title.textContent = task.title; const info = document.createElement("p"); info.textContent = `${task.status === "done" ? "Готово · " : ""}${formatDuration(totals.get(task.id) || 0)} учтено`; content.append(title, info); const select = document.createElement("button"); select.className = "text-button"; select.type = "button"; select.dataset.taskSelect = task.id; select.textContent = task.id === state.active_task_id ? "Активна" : "Выбрать"; const done = document.createElement("button"); done.className = "text-button"; done.type = "button"; done.dataset.taskDone = task.id; done.textContent = task.status === "done" ? "Вернуть" : "Готово"; row.append(content, select, done); list.append(row); });
}

async function loadTasks(state) { try { const [tasks, groups, summary] = await Promise.all([fetch("/api/tasks").then(response => response.json()), fetch("/api/task-groups").then(response => response.json()), fetch("/api/analytics/tasks").then(response => response.json())]); renderTasks(tasks.items, groups.items, state, summary.items); const old = $("#active-task-control"); if (old) old.remove(); const control = document.createElement("label"); control.id = "active-task-control"; control.className = "active-task-control"; control.textContent = "Учитывать время по задаче: "; const select = document.createElement("select"); const none = document.createElement("option"); none.value = ""; none.textContent = "Не выбрана"; select.append(none); tasks.items.filter(task => task.status !== "archived").forEach(task => { const option = document.createElement("option"); option.value = task.id; option.textContent = task.title; option.selected = task.id === state.active_task_id; select.append(option); }); select.addEventListener("change", () => postAction(select.value ? `/api/tasks/${select.value}/select` : "/api/tasks/clear-selection").catch(load)); control.append(select); $(".timer-stage").append(control); const previousFact = $("#task-plan-fact"); if (previousFact) previousFact.remove(); const totals = new Map(summary.items.map(item => [item.task_id, item.elapsed_seconds])); const fact = document.createElement("p"); fact.id = "task-plan-fact"; fact.className = "task-plan-fact"; const estimated = tasks.items.reduce((sum, task) => sum + (task.estimate_seconds || 0), 0); const actual = summary.items.reduce((sum, item) => sum + item.elapsed_seconds, 0); fact.textContent = `План / факт по задачам: ${formatDuration(estimated)} / ${formatDuration(actual)}`; $("#task-list").before(fact); } catch {} }

$("#task-form").addEventListener("submit", async event => { event.preventDefault(); const response = await fetch("/api/tasks", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ title: $("#task-title").value.trim(), group_id: $("#task-group").value ? Number($("#task-group").value) : null }) }); if (response.ok) { $("#task-title").value = ""; load(); } });
$("#group-form").addEventListener("submit", async event => { event.preventDefault(); const response = await fetch("/api/task-groups", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ name: $("#group-name").value.trim(), parent_id: $("#group-parent").value ? Number($("#group-parent").value) : null }) }); if (response.ok) { $("#group-name").value = ""; load(); } });
$("#task-list").addEventListener("click", async event => { const select = event.target.closest("[data-task-select]"); const done = event.target.closest("[data-task-done]"); if (select) await postAction(`/api/tasks/${select.dataset.taskSelect}/select`); if (done) { const task = (await fetch("/api/tasks").then(response => response.json())).items.find(item => item.id === Number(done.dataset.taskDone)); if (task) await fetch(`/api/tasks/${task.id}`, { method: "PUT", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ ...task, status: task.status === "done" ? "open" : "done" }) }); } load(); });

function renderHistory(days, tasks, scenarios, entries) { const summary = $("#history-summary"); summary.replaceChildren(); const total = days.reduce((sum, item) => sum + item.elapsed_seconds, 0); [["За последние дни", formatDuration(total)], ["Задач с учётом", String(tasks.filter(item => item.elapsed_seconds > 0).length)], ["Сценариев с историей", String(scenarios.length)]].forEach(([label, value]) => { const block = document.createElement("article"); block.className = "summary-block"; const title = document.createElement("p"); title.textContent = label; const number = document.createElement("strong"); number.textContent = value; block.append(title, number); summary.append(block); }); const list = $("#history-list"); list.replaceChildren(); entries.forEach(entry => { const row = document.createElement("article"); row.className = "history-row"; const content = document.createElement("div"); const title = document.createElement("h2"); title.textContent = entry.task_title || entry.phase_name || entry.scenario_name || "Свободная работа"; const details = document.createElement("p"); details.textContent = [entry.scenario_name, entry.phase_name, entry.started_at].filter(Boolean).join(" · "); const duration = document.createElement("time"); duration.textContent = formatDuration(entry.elapsed_seconds); content.append(title, details); row.append(content, duration); list.append(row); }); }
let historyFilter = "";
async function loadHistory() { try { const [days, tasks, scenarios, entries] = await Promise.all([fetch("/api/analytics/days").then(response => response.json()), fetch("/api/analytics/tasks").then(response => response.json()), fetch("/api/analytics/scenarios").then(response => response.json()), fetch(`/api/history${historyFilter}`).then(response => response.json())]); renderHistory(days.items, tasks.items, scenarios.items, entries.items); } catch {} }
$("#history-list").addEventListener("click", async event => { const button = event.target.closest("[data-entry-edit]"); if (!button) return; const minutes = prompt("Фактическое время, минут", String(Math.round(Number(button.dataset.entrySeconds) / 60))); if (minutes === null) return; const seconds = Math.round(Number(minutes) * 60); if (!Number.isFinite(seconds) || seconds < 0) return; const response = await fetch(`/api/history/${button.dataset.entryEdit}`, { method: "PATCH", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ elapsed_seconds: seconds }) }); if (response.ok) load(); });

const historyExport = document.createElement("a"); historyExport.className = "text-button"; historyExport.href = "/api/history.csv"; historyExport.textContent = "CSV-выгрузка";
document.querySelector('[data-panel="history"] .page-heading').append(historyExport);
const historyFilterForm = document.createElement("form"); historyFilterForm.className = "history-filter"; const from = document.createElement("input"); from.type = "date"; const to = document.createElement("input"); to.type = "date"; const apply = document.createElement("button"); apply.className = "button quiet small"; apply.type = "submit"; apply.textContent = "Фильтровать"; historyFilterForm.append("Период", from, to, apply); historyFilterForm.addEventListener("submit", event => { event.preventDefault(); const params = new URLSearchParams(); if (from.value) params.set("date_from", from.value); if (to.value) params.set("date_to", to.value); historyFilter = params.size ? `?${params}` : ""; historyExport.href = `/api/history.csv${historyFilter}`; loadHistory(); }); document.querySelector('[data-panel="history"] .page-heading').append(historyFilterForm);

["minimal", "scene"].forEach(name => { $(`#${name}-url`).value = `${location.origin}/overlay/${name}`; });
$$('[data-copy]').forEach(button => button.addEventListener("click", async () => { const input = $(`#${button.dataset.copy}`); await navigator.clipboard.writeText(input.value); const original = button.textContent; button.textContent = "Скопировано"; setTimeout(() => { button.textContent = original; }, 1200); }));

$$(".overlay-row").forEach((row, index) => { const preview = document.createElement("iframe"); preview.className = "overlay-preview"; preview.title = index === 0 ? "Предпросмотр минимального оверлея" : "Предпросмотр сценического оверлея"; preview.src = `/overlay/${index === 0 ? "minimal" : "scene"}`; row.append(preview); });

$("#preferences-form").addEventListener("submit", async event => {
  event.preventDefault();
  const response = await fetch("/api/preferences", {
    method: "PUT",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      sound_enabled: $("#pref-sound").checked,
      dnd: $("#pref-dnd").checked,
      warning_seconds: Number($("#pref-warning").value || 0),
      always_on_top: false,
      pomodoro_work_minutes: Number($("#pref-pomodoro-work").value || 25),
      pomodoro_break_minutes: Number($("#pref-pomodoro-break").value || 5),
      auto_start_next_phase: $("#pref-auto-start").checked,
      overlay_accent: $("#pref-overlay-accent").value,
    }),
  });
  if (response.ok) load();
});

function appendPhase(phase = { name: "Работа", duration_seconds: 1500, color_role: "work", repeat_policy: "every_cycle" }) {
  const row = document.createElement("div"); row.className = "phase-row"; row.draggable = true;
  const handle = document.createElement("span"); handle.className = "drag-handle"; handle.textContent = "⠿"; handle.setAttribute("aria-hidden", "true");
  const name = document.createElement("input"); name.name = "phase-name"; name.maxLength = 80; name.required = true; name.value = phase.name;
  const minutes = document.createElement("input"); minutes.name = "phase-minutes"; minutes.type = "number"; minutes.min = "1"; minutes.max = "1440"; minutes.required = true; minutes.value = String(Math.max(1, Math.round(phase.duration_seconds / 60)));
  const policy = document.createElement("select"); policy.name = "phase-policy";
  [["every_cycle", "Каждый цикл"], ["once_at_start", "Только в начале"], ["disabled", "Выключена"]].forEach(([value, label]) => { const option = document.createElement("option"); option.value = value; option.textContent = label; option.selected = phase.repeat_policy === value; policy.append(option); });
  const note = document.createElement("input"); note.name = "phase-note"; note.maxLength = 1000; note.placeholder = "Заметка (необязательно)"; note.value = phase.note || "";
  const remove = document.createElement("button"); remove.className = "icon-button"; remove.type = "button"; remove.textContent = "×"; remove.setAttribute("aria-label", "Удалить фазу"); remove.addEventListener("click", () => { if ($$(".phase-row", $("#phase-editor")).length > 1) row.remove(); });
  row.append(handle, name, minutes, policy, note, remove); $("#phase-editor").append(row);
  row.addEventListener("dragstart", () => row.classList.add("dragging")); row.addEventListener("dragend", () => row.classList.remove("dragging"));
}

function renderEditor(scenario) {
  const editor = $("#phase-editor"); editor.replaceChildren();
  $("#scenario-name").value = scenario ? scenario.name : "";
  $("#editor-title").textContent = scenario ? scenario.name : "Новый сценарий";
  $("#duplicate-scenario").disabled = !scenario; $("#archive-scenario").disabled = !scenario;
  (scenario ? scenario.phases : [{ name: "Работа", duration_seconds: 1500, color_role: "work", repeat_policy: "every_cycle" }]).forEach(appendPhase);
}

$("#phase-editor").addEventListener("dragover", event => { event.preventDefault(); const dragging = $(".phase-row.dragging", $("#phase-editor")); const target = event.target.closest(".phase-row"); if (dragging && target && dragging !== target) $("#phase-editor").insertBefore(dragging, target); });
$("#add-phase").addEventListener("click", () => appendPhase());
$("#new-scenario").addEventListener("click", () => { editingScenarioId = null; renderEditor(null); });
for (const [preset, label] of [["stream", "Стрим"], ["deep-work", "Глубокая работа"], ["pomodoro", "Pomodoro 25/5"]]) {
  const button = document.createElement("button"); button.className = "text-button"; button.type = "button"; button.textContent = label;
  button.addEventListener("click", async () => { const response = await fetch(`/api/scenarios/presets/${preset}`, { method: "POST" }); if (response.ok) { editingScenarioId = (await response.json()).id; load(); } });
  $("#new-scenario").parentElement.append(button);
}
$("#scenario-editor").addEventListener("submit", async event => { event.preventDefault(); const rows = $$(".phase-row", $("#phase-editor")); const payload = { name: $("#scenario-name").value.trim(), phases: rows.map(row => ({ name: $("[name=phase-name]", row).value.trim(), duration_seconds: Number($("[name=phase-minutes]", row).value) * 60, color_role: "custom", repeat_policy: $("[name=phase-policy]", row).value, note: $("[name=phase-note]", row).value.trim() })) }; const url = editingScenarioId ? `/api/scenarios/${editingScenarioId}` : "/api/scenarios"; const response = await fetch(url, { method: editingScenarioId ? "PUT" : "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(payload) }); if (response.ok) { const scenario = await response.json(); editingScenarioId = scenario.id; await postAction(`/api/scenarios/${scenario.id}/select`); await load(); } });
$("#duplicate-scenario").addEventListener("click", async () => { if (!editingScenarioId) return; const response = await fetch(`/api/scenarios/${editingScenarioId}/duplicate`, { method: "POST" }); if (response.ok) { editingScenarioId = (await response.json()).id; load(); } });
$("#archive-scenario").addEventListener("click", async () => { if (!editingScenarioId) return; const response = await fetch(`/api/scenarios/${editingScenarioId}`, { method: "DELETE" }); if (response.ok) { editingScenarioId = null; load(); } });

const autoStartLabel = document.createElement("label"); const autoStartInput = document.createElement("input"); autoStartInput.id = "pref-auto-start"; autoStartInput.type = "checkbox"; autoStartLabel.append(autoStartInput, " Автоматически запускать следующую фазу"); $("#preferences-form").insertBefore(autoStartLabel, $("#preferences-form button"));
const accentLabel = document.createElement("label"); accentLabel.textContent = "Акцент OBS: "; const accentInput = document.createElement("input"); accentInput.id = "pref-overlay-accent"; accentInput.type = "color"; accentInput.value = "#22c7ff"; accentLabel.append(accentInput); $("#preferences-form").insertBefore(accentLabel, $("#preferences-form button"));

function addHistoryEditButtons() {
  $$(".history-row", $("#history-list")).forEach((row, index) => {
    if (row.querySelector("[data-entry-edit]")) return;
    const entry = historyEntriesCache[index];
    if (!entry) return;
    const button = document.createElement("button");
    button.className = "text-button"; button.type = "button";
    button.dataset.entryEdit = entry.id; button.dataset.entrySeconds = entry.elapsed_seconds;
    button.textContent = "Исправить";
    row.append(button);
  });
}
let historyEntriesCache = [];
const originalRenderHistory = renderHistory;
renderHistory = function(days, tasks, scenarios, entries) { historyEntriesCache = entries; originalRenderHistory(days, tasks, scenarios, entries); addHistoryEditButtons(); };

const originalHistoryRenderForCharts = renderHistory;
renderHistory = function(days, tasks, scenarios, entries) {
  originalHistoryRenderForCharts(days, tasks, scenarios, entries);
  const existing = $("#history-charts"); if (existing) existing.remove();
  const charts = document.createElement("section"); charts.id = "history-charts"; charts.className = "history-charts";
  const maxDay = Math.max(1, ...days.map(item => item.elapsed_seconds)); const maxTask = Math.max(1, ...tasks.map(item => item.elapsed_seconds));
  const makeChart = (title, items, label, max) => { const block = document.createElement("article"); const heading = document.createElement("h2"); heading.textContent = title; block.append(heading); items.slice(0, 7).forEach(item => { const row = document.createElement("div"); row.className = "chart-row"; const name = document.createElement("span"); name.textContent = item[label]; const bar = document.createElement("i"); bar.style.width = `${Math.max(2, Math.round(item.elapsed_seconds / max * 100))}%`; const value = document.createElement("time"); value.textContent = formatDuration(item.elapsed_seconds); row.append(name, bar, value); block.append(row); }); return block; };
  charts.append(makeChart("По дням", days, "day", maxDay), makeChart("По задачам", tasks, "title", maxTask)); $("#history-summary").after(charts);
};

let taskItemsCache = [];
const originalRenderTasks = renderTasks;
renderTasks = function(tasks, groups, state, summary) {
  taskItemsCache = tasks;
  originalRenderTasks(tasks, groups, state, summary);
  $$(".task-row", $("#task-list")).forEach((row, index) => {
    const task = tasks[index]; if (!task) return;
    const edit = document.createElement("button"); edit.className = "text-button"; edit.type = "button"; edit.dataset.taskEdit = task.id; edit.textContent = "Изменить";
    row.append(edit);
  });
};
$("#task-list").addEventListener("click", async event => {
  const button = event.target.closest("[data-task-edit]"); if (!button) return;
  const task = taskItemsCache.find(item => item.id === Number(button.dataset.taskEdit)); if (!task) return;
  const title = prompt("Название задачи", task.title); if (title === null || !title.trim()) return;
  const description = prompt("Описание", task.description || ""); if (description === null) return;
  const tags = prompt("Теги через запятую", (task.tags || []).join(", ")); if (tags === null) return;
  const estimate = prompt("Оценка, минут (пусто — без оценки)", task.estimate_seconds ? String(Math.round(task.estimate_seconds / 60)) : ""); if (estimate === null) return;
  const estimateMinutes = estimate.trim() ? Number(estimate) : null;
  const response = await fetch(`/api/tasks/${task.id}`, { method: "PUT", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ ...task, title: title.trim(), description, tags: tags.split(",").map(tag => tag.trim()).filter(Boolean), estimate_seconds: estimateMinutes && Number.isFinite(estimateMinutes) ? Math.round(estimateMinutes * 60) : null }) });
  if (response.ok) load();
});
