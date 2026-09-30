export const $ = (selector, root = document) => root.querySelector(selector);
export const $$ = (selector, root = document) => [...root.querySelectorAll(selector)];
export const store = {state: {}, scenarios: [], tasks: [], groups: [], preferences: {}, token: '', connected: false};
export function node(tag, text = '', className = '') { const el = document.createElement(tag); el.textContent = text; if (className) el.className = className; return el; }
export function button(text, action, className = 'button small') { const el = node('button', text, className); el.type = 'button'; el.addEventListener('click', () => perform(action, el)); return el; }
export function message(text, error = false) { const el = $(error ? '#error' : '#notice'); el.textContent = text; el.hidden = !text; if (!error) $('#error').hidden = true; }
export async function perform(action, control) { if (control?.disabled) return; if (control) control.disabled = true; try { return await action(); } catch (e) { message(e.message || 'Не удалось выполнить действие', true); } finally { if (control) control.disabled = false; } }
export async function api(path, method = 'GET', payload) {
  const headers = {'X-WorkTimer-Token': store.token}; if (payload !== undefined) headers['Content-Type'] = 'application/json';
  let response; try { response = await fetch(path, {method, headers, body: payload === undefined ? undefined : JSON.stringify(payload)}); } catch { throw new Error('Нет связи с WorkTimer. Проверьте, что приложение запущено.'); }
  if (!response.ok) { let data; try { data = await response.json(); } catch {} const detail = data?.detail; throw new Error(Array.isArray(detail) ? detail.map(x => `${x.loc.slice(1).join('.')}: ${x.msg}`).join('; ') : detail || `Ошибка ${response.status}`); }
  if (response.status === 204) return null; return response.json();
}
export function duration(seconds = 0) { const s = Math.max(0, Math.floor(seconds)); const h = Math.floor(s / 3600), m = Math.floor(s / 60) % 60; return h ? `${h} ч ${m} мин` : m ? `${m} мин ${s % 60 ? `${s % 60} с` : ''}`.trim() : `${s} с`; }
export function setOptions(select, items, placeholder, label = x => x.name) { const value = select.value; select.replaceChildren(new Option(placeholder, ''), ...items.map(x => new Option(label(x), x.id))); if ([...select.options].some(x => x.value === value)) select.value = value; }
export function groupName(id) { const g = store.groups.find(x => x.id === id); const parent = store.groups.find(x => x.id === g?.parent_id); return g ? `${parent ? `${parent.name} / ` : ''}${g.name}` : 'Без группы'; }
export async function reloadData() { const [s,t,g] = await Promise.all([api('/api/scenarios'),api('/api/tasks?include_archived=true'),api('/api/task-groups')]); Object.assign(store, {scenarios:s.items,tasks:t.items,groups:g.items}); document.dispatchEvent(new Event('datachanged')); }
export function updateState(value) { store.state = value; document.dispatchEvent(new Event('statechanged')); }
export async function timerAction(name, payload) { updateState(await api(`/api/timer/${name}`, 'POST', payload));if(name==='add-cycle')await reloadData(); }
export async function download(path, filename) { const response = await fetch(path, {headers: {'X-WorkTimer-Token': store.token}}); if (!response.ok) throw new Error('Выгрузка не удалась'); const blob = await response.blob(); const url = URL.createObjectURL(blob), a = node('a'); a.href = url; a.download = filename; a.click(); setTimeout(() => URL.revokeObjectURL(url), 1000); }
export function field(label, control) { const el = node('label', label); control.setAttribute('aria-label',label); el.append(control); return el; }
export function input(type, value = '', props = {}) { const el = node('input'); el.type = type; el.value = value ?? ''; Object.assign(el, props); return el; }
let dialogSave;
export function openDialog(title, fields, save) { $('#dialog-title').textContent = title; $('#dialog-fields').replaceChildren(...fields); $('#dialog-error').textContent = ''; dialogSave = save; $('#form-dialog').showModal(); }
$('#dialog-form').addEventListener('submit', async e => { e.preventDefault(); const submit = $('button[type=submit]', e.target); submit.disabled = true; try { await dialogSave(); $('#form-dialog').close(); } catch (error) { $('#dialog-error').textContent = error.message; } finally { submit.disabled = false; } });
for (const id of ['close-dialog','cancel-dialog']) $(`#${id}`).addEventListener('click', () => $('#form-dialog').close());
