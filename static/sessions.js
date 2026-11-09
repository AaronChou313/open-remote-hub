'use strict';
window.RemoteHubSessions=(()=>{
 let version=0;
 function close(){version++}
 async function render(me,api,isCurrent){
  const mine=++version,d=await api('/zellij');if(mine!==version||!isCurrent())return;
  const running=d.sessions.filter(s=>s.status==='running').length;
  document.querySelector('#content').innerHTML=`${d.warning?`<p class="session-warning" role="status">${esc(d.warning)}</p>`:''}<div class="sessions-heading"><span>${running} 个运行中 · ${d.sessions.length-running} 个已退出</span>${me.role==='admin'?`<button class="primary" id="createSession">${icon('plus')}新建会话</button>`:''}</div><div class="session-grid">${d.sessions.map(s=>`<article class="session-card"><div class="session-card-title"><h2 class="mono">${esc(s.name)}</h2><span class="badge ${s.status}">${s.status==='running'?'运行中':'已退出'}</span></div>${s.pid?`<p class="mono muted">PID ${s.pid}</p>`:'<p class="muted">已保存会话</p>'}${me.role==='admin'?`<div class="toolbar"><a class="button primary" href="/terminal/open/${encodeURIComponent(s.name)}" target="_blank" rel="noopener">${s.status==='running'?'进入终端':'恢复并进入'} ${icon('external')}</a>${s.status==='running'?'<button data-session-action="rename">重命名</button><button data-session-action="kill">结束</button><button class="danger" data-session-action="purge">结束并删除</button>':'<button class="danger" data-session-action="delete">删除历史</button>'}</div>`:''}</article>`).join('')||empty('暂无会话')}</div>`;
  document.querySelectorAll('.session-card').forEach((card,i)=>card.querySelectorAll('[data-session-action]').forEach(b=>b.onclick=()=>act('zellij',d.sessions[i].name,b.dataset.sessionAction,b)));
  if(document.querySelector('#createSession'))document.querySelector('#createSession').onclick=()=>{$('#sessionForm').reset();$('#sessionError').textContent='';$('#sessionName').maxLength=me.host.system==='Darwin'?20:48;$('#sessionDialog').showModal();$('#sessionName').focus()};
 }
 return {render,close};
})();
