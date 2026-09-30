import {$,$$,store,api,perform,message,reloadData,updateState} from './shared.js';
import './timer-view.js';import './scenarios.js';import './tasks.js';import './history.js';import './overlays.js';import './about.js';import './updates.js';import {loadPreferences} from './settings.js';
let stream,quitting=false,polling=false,lastEvent=0;
const names={now:'Текущая сессия',scenarios:'Ритм работы',tasks:'План и факт',history:'Фактическое время',stream:'Для стрима',settings:'Приложение',about:'Справка и поддержка',developer:'Автор проекта'};
function showView(view){if(!(view in names))return;for(const panel of $$('[data-panel]'))panel.classList.toggle('is-visible',panel.dataset.panel===view);for(const nav of $$('.nav-item')){nav.classList.toggle('is-active',nav.dataset.view===view);if(nav.dataset.view===view)nav.setAttribute('aria-current','page');else nav.removeAttribute('aria-current');}$('#view-kicker').textContent=names[view];document.dispatchEvent(new CustomEvent('viewchanged',{detail:view}));$('#main').focus({preventScroll:true});}
for(const el of $$('[data-view]'))el.addEventListener('click',()=>{showView(el.dataset.view);history.replaceState(null,'',`#${el.dataset.view}`);});
window.addEventListener('hashchange',()=>showView(location.hash.slice(1)));showView(location.hash.slice(1));
function connection(ok){store.connected=ok;$('#connection-label').textContent=ok?'● На связи':'○ Нет связи · переподключение';}
async function bootstrap(){const data=await api('/api/bootstrap');store.token=data.token;store.preferences=data.preferences;loadPreferences();await reloadData();updateState(data.state);connection(true);if(data.migration_warning)message(data.migration_warning,true);}
function connect(){stream?.close();stream=new EventSource('/api/events');stream.addEventListener('state',e=>{try{updateState(JSON.parse(e.data));lastEvent=Date.now();connection(true);}catch{}});stream.onerror=()=>connection(false);stream.onopen=()=>perform(async()=>{await bootstrap();lastEvent=Date.now();});}
setInterval(async()=>{if(quitting||polling||Date.now()-lastEvent<2500)return;polling=true;try{if(!store.connected)await bootstrap();updateState(await api('/api/state'));connection(true);}catch{connection(false);}finally{polling=false;}},3000);
document.addEventListener('appquitting',()=>{quitting=true;stream?.close();});
perform(async()=>{await bootstrap();connect();});
