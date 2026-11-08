'use strict';
window.RemoteHubSessions=(()=>{
 let selected=localStorage.getItem('orh-session')||'',rows=[],version=0,selection=0,role='admin',tabStates=new Map(),invoke;
 function close(){version++;selection++}
 const status=s=>s==='running'?'运行中':'已退出';
 function actions(s){return `<div class="toolbar"><a class="button primary" href="/terminal/open/${encodeURIComponent(s.name)}" target="_blank" rel="noopener">${s.status==='running'?'打开终端 ↗':'恢复并进入 ↗'}</a>${s.status==='running'?'<button data-session-action="rename">重命名</button><button data-session-action="kill">结束会话</button><button class="danger" data-session-action="purge">结束并删除</button>':'<button class="danger" data-session-action="delete">删除历史</button>'}</div>`}
 function summary(s){return `<div class="session-detail-heading"><div><small>会话 / Session</small><h2 class="mono">${esc(s.name)}</h2><span class="badge ${s.status}">${status(s.status)}</span>${s.pid?`<small class="mono"> · PID ${s.pid}</small>`:''}</div>${role==='admin'?actions(s):''}</div>`}
 async function detail(){
  const s=rows.find(r=>r.name===selected),request=++selection,mine=version,host=document.querySelector('#sessionDetail');
  if(!host)return;if(!s){host.innerHTML=empty('还没有终端会话');return}
  const valid=()=>request===selection&&mine===version&&selected===s.name&&!!document.querySelector('#sessionDetail');
  host.innerHTML=summary(s)+(s.status==='running'&&role==='admin'?'<div id="sessionStructure" class="session-structure">正在读取标签页…</div>':'');
  host.querySelectorAll('[data-session-action]').forEach(b=>b.onclick=()=>act('zellij',s.name,b.dataset.sessionAction,b));
  if(s.status!=='running'||role!=='admin')return;
  try{
   const d=await invoke('/zellij/'+encodeURIComponent(s.name)+'/structure');if(!valid())return;
   const count=d.tabs.reduce((n,t)=>n+t.panes.length,0);
   const target=document.querySelector('#sessionStructure');
   target.innerHTML=`<div class="structure-heading"><span>${d.tabs.length} 个标签页 · ${count} 个终端窗格</span><button id="newTab">＋ 标签页</button></div>${d.tabs.map((t,i)=>`<details class="terminal-tab" data-tab="${t.id}" ${(tabStates.has(s.name+':'+t.id)?tabStates.get(s.name+':'+t.id):i===0)?'open':''}><summary><span><small>Tab ${t.position+1}</small> ${esc(t.name)}</span><small>${t.pending?'待终端连接':t.panes.length+' Pane'}</small></summary><div class="tab-actions toolbar"><button data-tab-action="pane" data-tab="${t.id}">＋ 终端窗格</button><button data-tab-action="rename" data-tab="${t.id}" data-name="${esc(t.name)}">重命名标签页</button><button class="danger" data-tab-action="close" data-tab="${t.id}" data-name="${esc(t.name)}">关闭标签页</button></div><div class="pane-list">${t.panes.map(p=>`<article class="pane-row"><div class="pane-label"><strong>${esc(p.title)}</strong><small class="mono">${esc(p.id)}</small>${p.focused?'<span class="badge">当前</span>':''}${p.held?'<span class="badge">等待恢复</span>':p.exited?'<span class="badge">已退出</span>':''}${p.floating?'<span class="badge">浮动</span>':''}</div>${p.command?`<code class="pane-command">${esc(p.command)}</code>`:''}${p.cwd?`<small class="pane-cwd">${esc(p.cwd)}</small>`:''}<div class="toolbar"><button data-pane-output="${esc(p.id)}">查看输出</button><button class="danger" data-pane-close="${esc(p.id)}" data-name="${esc(p.title)}">关闭窗格</button></div></article>`).join('')||'<p class="muted">没有终端窗格</p>'}</div>${t.plugins.length?`<details class="pane-plugins"><summary>界面插件 · ${t.plugins.length}</summary>${t.plugins.map(p=>`<p><span class="mono">${esc(p.id)}</span> · ${esc(p.title)}</p>`).join('')}</details>`:''}</details>`).join('')}`;
   target.querySelectorAll('.terminal-tab').forEach(el=>el.ontoggle=()=>{const key=s.name+':'+el.dataset.tab;tabStates.set(key,el.open)});
   document.querySelector('#newTab').onclick=b=>change('tabs','create','',b.currentTarget);
   target.querySelectorAll('[data-tab-action]').forEach(b=>b.onclick=()=>change('tabs/'+b.dataset.tab,b.dataset.tabAction,b.dataset.name||'',b));
   target.querySelectorAll('[data-pane-close]').forEach(b=>b.onclick=()=>change('panes/'+b.dataset.paneClose,'close',b.dataset.name,b));
   target.querySelectorAll('[data-pane-output]').forEach(b=>b.onclick=()=>withBusy(b,'output:'+s.name+':'+b.dataset.paneOutput,'读取中…',async()=>{try{const d=await invoke('/zellij/'+encodeURIComponent(s.name)+'/output?pane='+encodeURIComponent(b.dataset.paneOutput));output(s.name+' / '+b.dataset.paneOutput,d.output)}catch(e){showError(e)}}));
  }catch(e){if(valid())document.querySelector('#sessionStructure').textContent=e.message}
 }
 async function change(path,action,label,button){
  const name=selected;let title='';
  if(action==='create'||action==='rename'){title=await requestName(action==='create'?'新建标签页':'重命名标签页',label,action==='create'?'创建':'保存');if(title===null||!title.trim())return}
  if(action==='close'&&!await confirmAction('关闭 '+(label||path),`会话：${name}\n${path.startsWith('tabs')?'该标签页的所有窗格和任务都将结束。':'该窗格中的任务将结束。'}`))return;
  await withBusy(button,'session:'+name,'处理中…',async()=>{try{await invoke('/zellij/'+encodeURIComponent(name)+'/'+path,{action,name:title,confirm:name});await refresh()}catch(e){showError(e)}});
 }
 async function render(me,api,isCurrent){
  invoke=api;role=me.role;const mine=++version;
  const d=await api('/zellij');if(mine!==version||!isCurrent())return;
  rows=d.sessions;
  if(!rows.some(s=>s.name===selected))selected=rows[0]?.name||'';
  document.querySelector('#content').innerHTML=`${d.warning?`<p class="session-warning" role="status">${esc(d.warning)}</p>`:''}<div class="session-workspace"><section class="panel sessions-list"><div class="panel-head"><h2>会话 <small>${rows.length}</small></h2>${role==='admin'?'<button class="primary" id="createSession">＋ 新建</button>':''}</div>${['running','exited'].map(state=>{const group=rows.filter(s=>s.status===state);return group.length?`<div class="session-group-label">${status(state)}</div>${group.map(s=>`<button class="session-list-row ${s.name===selected?'selected':''}" data-session="${esc(s.name)}" aria-pressed="${s.name===selected}"><strong class="mono">${esc(s.name)}</strong><span class="session-state ${state}">${status(state)}</span></button>`).join('')}`:''}).join('')||empty('暂无会话')}</section><section class="panel session-detail" id="sessionDetail"></section></div>`;
  document.querySelectorAll('[data-session]').forEach(b=>b.onclick=()=>{selected=b.dataset.session;localStorage.setItem('orh-session',selected);document.querySelectorAll('[data-session]').forEach(x=>{x.classList.toggle('selected',x===b);x.setAttribute('aria-pressed',x===b?'true':'false')});detail()});
  if(document.querySelector('#createSession'))document.querySelector('#createSession').onclick=()=>{$('#sessionForm').reset();$('#sessionError').textContent='';$('#sessionName').maxLength=me.host.system==='Darwin'?20:48;$('#sessionDialog').showModal();$('#sessionName').focus()};
  await detail();
 }
 return {render,close};
})();
