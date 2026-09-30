import {$,api,perform,message,node,openDialog} from './shared.js';

let current,stopped=false,pending=false,restarting=false;
function render(value){
  current=value;
  const busy=['checking','downloading','installing'].includes(value.status);
  $('#update-status').textContent=value.message;
  $('#check-updates').disabled=busy||value.check_retry_after>0;
  $('#check-updates').textContent=!busy&&value.check_retry_after>0?`Проверить снова · ${value.check_retry_after} с`:'Проверить обновления';
  $('#install-update').hidden=!value.can_install||!value.latest_version||!['available','error','downloading','installing'].includes(value.status);
  $('#install-update').disabled=busy;
  $('#install-update').textContent=value.latest_version?`Обновить до ${value.latest_version}`:'Обновить программу';
  $('#release-link').href=value.releases_url;
  $('#update-install-note').textContent=value.can_install?'Перед установкой сессия сохранится на паузе, а база — в резервной копии. После обновления WorkTimer запустится снова.':'Для portable-версии скачайте новый архив из релизов и распакуйте его в новую папку. Данные сохранятся. Установка из исходников обновляется разработчиком.';
  const progress=$('#update-progress');
  progress.hidden=value.status!=='downloading';
  progress.value=value.total?Math.min(100,value.downloaded/value.total*100):0;
  if(!progress.hidden)$('#update-status').textContent=`${value.message} ${Math.round(progress.value)}%`;
  const available=Boolean(value.latest_version);
  $('#update-banner').hidden=!available;
  $('#update-banner-text').textContent=value.status==='installing'?'Устанавливаем обновление. WorkTimer перезапустится…':`Доступна новая версия WorkTimer ${value.latest_version}.`;
  if(value.status==='installing')restarting=true;
}
$('#check-updates').addEventListener('click',()=>perform(async()=>render(await api('/api/updates/check','POST'))));
$('#install-update').addEventListener('click',()=>{
  if(!current?.can_install||!current.latest_version)return;
  openDialog(`Обновить WorkTimer до ${current.latest_version}?`,[node('p','Программа скачает установщик с GitHub, проверит файл и сохранит резервную копию данных. Таймер будет на паузе. WorkTimer закроется и запустится после установки.')],async()=>{
    render(await api('/api/updates/install','POST'));
    restarting=true;
    message('Обновление скачивается. WorkTimer перезапустится после установки; сессия сохранится на паузе.');
  },'Скачать и установить');
});
async function poll(){
  if(stopped||pending)return;
  pending=true;
  try{
    const value=await api('/api/updates');
    if(restarting&&value.current_version!==current?.current_version){location.reload();return;}
    render(value);
    if(value.status==='error')restarting=false;
  }catch{
    if(restarting)$('#update-status').textContent='Ожидаем перезапуск WorkTimer после установки…';
  }finally{pending=false;}
}
document.addEventListener('appquitting',()=>stopped=true);
document.addEventListener('viewchanged',e=>{if(e.detail==='about')poll();});
setInterval(poll,2000);
poll();
