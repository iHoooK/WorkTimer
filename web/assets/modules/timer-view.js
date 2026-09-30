import {$,store,node,button,setOptions,duration,api,perform,timerAction,updateState} from './shared.js';
const labels = {idle:'Ожидание',running:'Идёт',paused:'На паузе',finished:'Фаза завершена'};
function render() {
  const s = store.state, free = s.mode === 'free', scenario = store.scenarios.find(x => x.id === s.scenario_id);
  $('#phase-name').textContent = s.phase_name || 'Готов к началу'; $('#timer-value').textContent = s.time || '00:00';
  const status = s.scenario_completed ? 'Сессия завершена' : labels[s.phase] || 'Ожидание'; if ($('#timer-status').textContent !== status) $('#timer-status').textContent = status;
  $('#phase-note').textContent = s.phase_note || ''; $('#next-copy').textContent = free ? 'Свободный таймер считает время до завершения сессии.' : s.scenario_completed ? 'Все рабочие циклы завершены. Можно добавить ещё один.' : s.next_phase_name ? `Далее: ${s.next_phase_name}` : 'Создайте сценарий или запустите свободный таймер.';
  $('#progress-track').hidden = free; $('#progress-value').style.width = `${Math.min(100,Math.max(0,(s.progress || 0)*100))}%`; $('#progress-track').setAttribute('aria-valuenow', Math.round((s.progress || 0)*100));
  $('#cycle-count').textContent = s.progress_total ? `Рабочий цикл ${s.progress_current || 0} из ${s.progress_total}` : free ? 'Без ограничения времени' : scenario ? 'Циклы без ограничения' : '';
  $('#add-cycle').hidden = !s.progress_total; $('#add-cycle').disabled = s.progress_total >= 100;
  $('#recovery').hidden = !s.recovered; $('#toggle-timer').textContent = s.phase === 'running' ? 'Пауза' : s.phase === 'paused' ? 'Продолжить' : s.phase === 'finished' ? 'Продолжить сценарий' : 'Начать';
  $('#toggle-timer').disabled = (!free && !scenario) || !!s.scenario_completed; $('#next-phase').disabled = free || !scenario || !!s.scenario_completed;
  $('#stop-timer').disabled = !s.session_id && ['idle',undefined].includes(s.phase); $('#repeat-phase').disabled = free || !s.current_phase_id; $('#restart-scenario').disabled = free || !scenario;
  $('#scenario-heading').textContent = free ? 'Свободный режим' : s.scenario_name || 'Выберите ритм работы'; $('#active-scenario').value = s.scenario_id || ''; $('#active-task').value = s.active_task_id || '';
  const task = store.tasks.find(x => x.id === s.active_task_id); $('#task-context').textContent = task ? `Следующий рабочий отрезок: ${task.title}` : 'Можно работать без задачи.';
  $('#onboarding').hidden = store.scenarios.some(x => !x.is_archived);
  for (const [id,mode] of [['scenario-mode','scenario'],['pomodoro-timer','pomodoro'],['free-timer','free']]) { $(`#${id}`).classList.toggle('is-active',s.mode === mode); $(`#${id}`).setAttribute('aria-pressed',String(s.mode === mode)); }
  const key = JSON.stringify([scenario,s.current_phase_id,s.progress_current]); if ($('#phase-list').dataset.key !== key) { $('#phase-list').dataset.key = key; $('#phase-list').replaceChildren(...(scenario?.phases || []).map((p,i) => { const li = node('li', '', p.id === s.current_phase_id ? 'current' : p.repeat_policy === 'disabled' ? 'disabled' : ''); const start=button('Запустить',()=>timerAction(`phase/${p.position}`),'text-button');start.setAttribute('aria-label',`Запустить фазу ${p.name}`);start.disabled=p.repeat_policy==='disabled'||(p.progress_marker&&s.progress_total>0&&s.progress_current>=s.progress_total);li.append(node('span',`${i+1}. ${p.name}${p.repeat_policy==='once_at_start'?' · один раз':''}`),node('time',duration(p.duration_seconds)),start); return li; })); }
}
document.addEventListener('statechanged',render);
document.addEventListener('datachanged', () => { setOptions($('#active-scenario'),store.scenarios.filter(x=>!x.is_archived),'Без сценария'); setOptions($('#active-task'),store.tasks.filter(x=>x.status!=='archived'),'Без задачи',x=>x.title); render(); });
for (const [id,action] of [['toggle-timer','toggle'],['next-phase','next'],['repeat-phase','repeat'],['restart-scenario','restart'],['stop-timer','stop'],['add-cycle','add-cycle'],['free-timer','free']]) $(`#${id}`).addEventListener('click', () => perform(() => timerAction(action),$(`#${id}`)));
$('#pomodoro-timer').addEventListener('click',()=>perform(async()=> { const p=store.preferences; await timerAction('pomodoro',{work_seconds:p.pomodoro_work_minutes*60,break_seconds:p.pomodoro_break_minutes*60,long_break_seconds:p.pomodoro_long_break_minutes*60,cycles_before_long_break:p.pomodoro_cycles_before_long_break}); const {reloadData}=await import('./shared.js'); await reloadData(); },$('#pomodoro-timer')));
$('#active-scenario').addEventListener('change',e=>perform(async()=> { if(e.target.value) updateState(await api(`/api/scenarios/${e.target.value}/select`,'POST')); }));
$('#scenario-mode').addEventListener('click',()=>perform(async()=> { const s=store.scenarios.find(x=>!x.is_archived); if(s) updateState(await api(`/api/scenarios/${s.id}/select`,'POST')); else document.querySelector('[data-view=scenarios]').click(); }));
$('#active-task').addEventListener('change', e=>perform(async()=>updateState(await api(e.target.value?`/api/tasks/${e.target.value}/select`:'/api/tasks/clear-selection','POST'))));
