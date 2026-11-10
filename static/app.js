'use strict';
const $=s=>document.querySelector(s), esc=s=>String(s??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const bytes=n=>{n=Number(n);if(!Number.isFinite(n))return '—';const units=['B','KB','MB','GB','TB'];let i=0;while(n>=1024&&i<4){n/=1024;i++}return `${n.toFixed(i?1:0)} ${units[i]}`};
const uptime=s=>{s=Math.max(0,s);return `${Math.floor(s/86400)} 天 ${Math.floor(s%86400/3600)} 小时`};
let renderVersion=0;
let view=typeof location!=='undefined'&&location.hash==='#proxy'?'proxy':localStorage.getItem('orh-view')||'overview', me, busy=false, stream, chartHours=1,refreshQueued=false;
const pendingOperations=new Set();
const titles={proxy:['代理与网络','管理机场配置、主机代理与网络连接。'],overview:['系统概览','实时掌握主机状态，让每一项任务尽在掌控。'],docker:['容器与镜像','连接 OrbStack / Docker，直接管理本机容器。'],zellij:['终端管理','管理会话，进入原生终端。'],files:['文件管理','浏览主机文件，让目录、项目和终端相连。'],projects:['项目管理','本地项目、Git 状态与开发任务。'],environments:['开发环境','查看工具、项目环境与依赖。'],dsh:['DeepSeek Harness','使用本机 DSH 的原生工作空间。'],tasks:['任务与服务','明确的命令，可追踪的进程，由你管理的任务。']};
if(localStorage.getItem('orh-theme')==='dark'||(!localStorage.getItem('orh-theme')&&matchMedia('(prefers-color-scheme: dark)').matches))document.body.classList.add('dark');
async function api(path,body){const r=await fetch('/api'+path,{method:body===undefined?'GET':'POST',headers:body===undefined?{}:{'Content-Type':'application/json','X-ORH-Request':'1'},body:body===undefined?undefined:JSON.stringify(body),signal:AbortSignal.timeout(body===undefined?(path.startsWith('/environments')?30000:10000):(path.startsWith('/proxy/manager')?90000:60000))});let d;try{d=await r.json()}catch{throw Error('服务器返回异常响应')}if(r.status===401){showLogin();throw Error(d.detail||'请重新登录')}if(!r.ok){const error=Error(typeof d.detail==='string'?d.detail:JSON.stringify(d.detail));error.status=r.status;throw error}return d}
async function withBusy(button,key,label,work){
 if(pendingOperations.has(key))return;pendingOperations.add(key);
 const text=button?.textContent,markup=button?.innerHTML;
 if(button){button.disabled=true;button.textContent=label;button.setAttribute('aria-busy','true')}
 try{return await work()}finally{pendingOperations.delete(key);if(button?.isConnected){button.disabled=false;if(markup!==undefined)button.innerHTML=markup;else button.textContent=text;button.removeAttribute('aria-busy')}}
}
async function switchView(target){
 if(view!==target&&window.RemoteHubProxyManager&&!await RemoteHubProxyManager.canLeave())return;
 if(view!==target&&window.RemoteHubWorkspace&&!await RemoteHubWorkspace.canLeave())return;
 if(!titles[target])target='overview';
 if(target!==view)window.scrollTo?.(0,0);
 renderVersion++;busy=false;window.RemoteHubSessions?.close();view=target;localStorage.setItem('orh-view',view);
 document.querySelectorAll('nav button').forEach(x=>x.classList.toggle('active',x.dataset.view===view));
 $('#title').textContent=titles[view][0];$('#subtitle').textContent=titles[view][1];$('#breadcrumb').textContent='工作空间 / '+titles[view][0];
 $('#error').hidden=true;$('#content').innerHTML=empty('正在读取本机数据…');refresh();
}
function showLogin(){window.RemoteHubWorkspace?.reset();renderVersion++;busy=false;window.RemoteHubSessions?.close();$('#login').hidden=false;$('#shell').hidden=true;if(stream)stream.close();$('#content').replaceChildren();loadAuth()}
function notify(text){$('#toast').textContent=text;$('#toast').hidden=false;setTimeout(()=>$('#toast').hidden=true,3500)}
function showError(e,operation=true){$('#error').textContent=e.message;$('#error').dataset.kind=operation?'operation':'load';$('#error').hidden=false;if(!operation)$('#connection').textContent='更新失败 · 保留最近数据'}
async function confirmAction(title,message){if($('#confirmDialog').open)return false;$('#confirmTitle').textContent=title;$('#confirmMessage').textContent=message;$('#confirmDialog').returnValue='cancel';$('#confirmDialog').showModal();return new Promise(resolve=>$('#confirmDialog').addEventListener('close',()=>resolve($('#confirmDialog').returnValue==='confirm'),{once:true}))}
function requestName(title,value='',submit='保存',limit=80){
 const dialog=$('#nameDialog');if(dialog.open)return Promise.resolve(null);
 $('#nameTitle').textContent=title;$('#nameInput').value=value;$('#nameInput').maxLength=limit;$('#saveName').textContent=submit;dialog.returnValue='cancel';dialog.showModal();$('#nameInput').focus();$('#nameInput').select();
 return new Promise(resolve=>{dialog.onclose=()=>resolve(dialog.returnValue==='save'?$('#nameInput').value.trim():null);$('#nameForm').onsubmit=e=>{e.preventDefault();if($('#nameInput').value.trim())dialog.close('save')}});
}
function output(title,text){if(stream){stream.close();stream=null}$('#outputTitle').textContent=title;$('#output').textContent=text;$('#outputDialog').showModal()}
function panel(title,body,extra='',desc=''){return `<section class="panel"><div class="panel-head"><div><h2>${title}</h2>${desc?`<p>${desc}</p>`:''}</div>${extra}</div>${body}</section>`}
function table(head,rows){return `<div class="table-wrap"><table><thead><tr>${head.map(x=>`<th>${x}</th>`).join('')}</tr></thead><tbody>${rows.join('')}</tbody></table></div>`}
function empty(text){return `<div class="empty">${text}</div>`}
function badge(state){return `<span class="badge ${['running','exited'].includes(state)?state:''}">${esc(state)}</span>`}
function buttons(kind,id,actions){if(me.role!=='admin')return '<small>只读</small>';return actions.map(([action,label])=>`<button data-kind="${kind}" data-id="${esc(id)}" data-action="${action}" ${['stop','kill','delete'].includes(action)?'class="danger"':''}>${icon({start:'start',stop:'stop',restart:'refresh',delete:'delete',kill:'stop'}[action])}${label}</button>`).join('')}
function procTable(list){return table(['进程 / 命令','PID','CPU¹','内存','运行时间'],list.map(p=>`<tr><td class="command" title="${esc(p.command)}"><strong>${esc(p.name)}</strong><br><small class="mono">${esc(p.command)}</small></td><td class="mono">${p.pid}</td><td class="mono">${p.cpu.toFixed(1)}%</td><td class="mono">${bytes(p.memory)}</td><td>${uptime(Date.now()/1000-p.created)}</td></tr>`))}
function chart(data){if(data.length<2)return empty('正在采集真实数据，稍候即可查看趋势。');const w=900,h=170,left=34,right=12,top=15,bottom=28,start=data[0].time,end=data.at(-1).time;const x=t=>left+(t-start)/(end-start)*(w-left-right),y=v=>h-bottom-v/100*(h-top-bottom);const path=k=>data.map((p,i)=>`${i?'L':'M'}${x(p.time).toFixed(1)},${y(p[k]).toFixed(1)}`).join(' ');return `<svg class="chart" viewBox="0 0 ${w} ${h}" preserveAspectRatio="none" role="img" aria-label="CPU 与内存历史使用率">${[0,25,50,75,100].map(v=>`<line class="grid" x1="${left}" x2="${w-right}" y1="${y(v)}" y2="${y(v)}"/><text x="0" y="${y(v)+3}">${v}%</text>`).join('')}<path class="mem" d="${path('memory')}"/><path class="cpu" d="${path('cpu')}"/>${[0,.25,.5,.75,1].map(f=>`<text x="${left+f*(w-left-right)}" y="${h-4}" text-anchor="${f===0?'start':f===1?'end':'middle'}">${new Date((start+(end-start)*f)*1000).toLocaleTimeString('zh-CN',{hour:'2-digit',minute:'2-digit'})}</text>`).join('')}</svg>`}
async function overview(version){const [d,h]=await Promise.all([api('/system'),api('/history?hours='+chartHours)]);if(version!==renderVersion)return;const m=d.metrics,host=d.host;if(!m){$('#content').innerHTML=empty('正在进行首次系统采样…');return}$('#content').innerHTML=`<div class="host-strip"><span class="host-icon">${icon('server')}</span><div><strong>${esc(host.hostname)}</strong><small>${esc(host.system)} ${esc(host.version)} · ${esc(host.arch)} · ${host.cores} 核 CPU</small></div><div class="host-meta">${badge('running')}<br>已运行 ${uptime(Date.now()/1000-host.boot)}</div></div><div class="metrics">${[['CPU 使用率',m.cpu.toFixed(1),'%',`${host.cores} 个逻辑核心`,m.cpu],['内存使用率',m.memory.toFixed(1),'%',`${bytes(m.memory_used)} / ${bytes(m.memory_total)}`,m.memory],['磁盘使用率',m.disk.toFixed(1),'%',`${bytes(m.disk_used)} / ${bytes(m.disk_total)}`,m.disk],['网络吞吐',bytes(m.rx),'/s',`↑ ${bytes(m.tx)}/s  ·  ↓ 接收`,null]].map(([label,n,unit,detail,pct])=>`<div class="metric"><div class="metric-label">${label}<span>${icon(pct===null?'network':label.startsWith('CPU')?'cpu':label.startsWith('内存')?'memory':'disk')}</span></div><div class="metric-value">${n} <small>${unit}</small></div>${pct===null?'':`<div class="meter"><i style="width:${Math.min(100,pct)}%"></i></div>`}<small>${detail}</small></div>`).join('')}</div>${panel('资源趋势',`<div class="chart-wrap">${chart(h)}</div>`,`<div class="toolbar"><div class="legend"><span><b>●</b> CPU</span><span>● 内存</span></div><select id="historyHours" aria-label="历史时间范围">${[[1,'最近 1 小时'],[24,'最近 24 小时'],[168,'最近 7 天']].map(([v,l])=>`<option value="${v}" ${chartHours===v?'selected':''}>${l}</option>`).join('')}</select></div>`,'每 3 秒采样 · 本机 SQLite 保留 7 天')}${panel('活跃进程',procTable(d.processes.slice(0,25)),'<span class="badge">CPU 优先 · 前 25 项</span>','¹ 单进程 CPU 按逻辑核心计，可超过 100%。系统进程仅查看。')}`;$('#historyHours').onchange=e=>{chartHours=Number(e.target.value);refresh()};$('#updated').textContent='采样于 '+new Date(m.time*1000).toLocaleTimeString();if(d.error)throw Error(d.error)}
async function dockerView(version){const d=await api('/docker');if(version!==renderVersion)return;$('#content').innerHTML=panel('容器',d.containers.length?`<div class="container-grid">${d.containers.map(c=>{const s=d.stats.find(x=>x.ID===c.ID||c.ID.startsWith(x.ID)||x.Name===c.Names);return `<article class="container-card"><div class="container-heading"><h3 class="mono">${esc(c.Names)}</h3>${badge(c.State)}</div><p class="container-image mono">${esc(c.Image)}</p><p class="muted">${esc(c.Status)}</p><dl class="container-stats"><div><dt>CPU</dt><dd>${s?esc(s.CPUPerc):'—'}</dd></div><div><dt>内存</dt><dd>${s?esc(s.MemUsage):'—'}</dd></div></dl><div class="container-ports"><small>${c.State==='running'?'端口映射':'配置端口（未监听）'}</small><p class="mono">${esc(c.Ports||c.ConfiguredPorts)||'无映射'}</p></div><div class="toolbar">${buttons('docker',c.ID,c.State==='running'?[['stop','停止'],['restart','重启']]:[['start','启动']])}<button data-kind="docker" data-id="${c.ID}" data-action="detail" aria-label="${esc(c.Names)} 详情">详情</button><button data-kind="docker" data-id="${c.ID}" data-action="logs" aria-label="${esc(c.Names)} 日志">日志</button></div></article>`}).join('')}</div>`:empty('Docker 当前没有容器。'),`<span class="badge">${d.containers.length} 个容器</span>`,'资源占用来自 Docker 实时统计；停止的容器显示为空。')+panel('本地镜像',d.images.length?table(['镜像仓库','标签','大小','创建时间'],d.images.map(i=>`<tr><td class="mono">${esc(i.Repository)}</td><td>${esc(i.Tag)}</td><td>${esc(i.Size)}</td><td>${esc(i.CreatedSince)}</td></tr>`)):empty('暂无镜像'));}
async function zellijView(version){return RemoteHubSessions.render(me,api,()=>version===renderVersion)}
function mountTerminal(name){
 const url='/terminal/open/'+encodeURIComponent(name),tab=window.open(url,'_blank');
 if(tab){tab.opener=null;return true}
 $('#error').replaceChildren(document.createTextNode('浏览器阻止了新标签页。'));
 const link=document.createElement('a');link.href=url;link.target='_blank';link.rel='noopener';link.textContent='点击这里进入终端 ↗';$('#error').append(link);$('#error').hidden=false;return false;
}
async function tasksView(version){const [tasks,svc]=await Promise.all([api('/tasks'),api('/services')]);if(version!==renderVersion)return;$('#content').innerHTML=panel('我的快捷任务',tasks.length?table(['任务 / 启动命令','状态','PID / 运行时间','操作'],tasks.map(t=>`<tr><td class="command" title="${esc(JSON.stringify(t.argv))}"><strong>${esc(t.name)}</strong><br><code>${esc(JSON.stringify(t.argv))}</code><br><small>${esc(t.cwd)}</small></td><td>${badge(t.running?'running':'exited')}</td><td class="mono">${t.running?`${t.pid}<br>${uptime(Date.now()/1000-t.created)}`:'—'}</td><td><div class="toolbar">${buttons('tasks',t.id,t.running?[['stop','停止'],['restart','重启']]:[['start','启动'],['delete','移除']])}<button data-kind="tasks" data-id="${esc(t.id)}" data-action="logs">日志</button></div></td></tr>`)):empty('还没有管理中的任务。保存常用命令后，可以在这里启动和查看日志。'),me.role==='admin'?`<button class="primary" id="newTask">${icon('plus')}新建任务</button>`:'','只管理本控制台创建的独立进程组；现有后台服务不受任务按钮控制。')+panel('宿主机后台服务',table(['服务名称','PID','状态 / 退出码','来源 / 详情'],svc.services.map(s=>`<tr><td class="mono">${esc(s.name)}</td><td>${s.pid||'—'}</td><td>${s.status?esc(s.status):s.pid?badge('running'):`退出码 ${esc(s.exit)}`}</td><td>${esc(s.source)} · 只读 <button data-kind="services" data-id="${esc(s.name)}" data-action="detail">进程与日志</button></td></tr>`)),'','macOS 展示非 Apple 的用户 launchd 服务；点击详情查看进程命令、运行时间戳及配置的文件日志。');if($('#newTask'))$('#newTask').onclick=()=>{$('#taskForm').reset();$('#taskError').textContent='';$('#taskCwd').value=localStorage.getItem('orh-task-cwd')||'';$('#taskDialog').showModal();$('#taskName').focus()}}
async function act(kind,id,action,button){
 if(action==='open'){mountTerminal(id);return}
 let name='';
 if(action==='rename'){name=await requestName('重命名会话',id,'保存',me.host.system==='Darwin'?20:48);if(!name||name===id)return}
 const labels={start:'启动',stop:'停止',restart:'重启',create:'创建',kill:'结束',delete:'删除历史',purge:'结束并删除',rename:'重命名'};
 if(['stop','restart','kill','delete','purge'].includes(action)){
  const impact=action==='purge'?'会话内全部标签页、窗格和任务都会结束，并删除保存的历史。':action==='delete'?(kind==='zellij'?'删除已保存的会话布局和历史记录，无法撤销。':'移除任务配置，无法撤销。'):'此操作会中断目标中正在执行的任务。';
  const display=button?.closest('.container-card')?.querySelector('h3')?.textContent||button?.closest('tr')?.querySelector('strong')?.textContent||id;
  if(!await confirmAction(labels[action]+' '+display,impact))return;
 }
 return withBusy(button,kind+':'+id,labels[action]?labels[action]+'中…':'读取中…',async()=>{
  try{
   if(action==='detail'){output(kind==='services'?'服务进程与日志':'容器详情 · 端口与挂载',JSON.stringify(await api('/'+kind+'/'+encodeURIComponent(id)),null,2));return}
   if(action==='logs'){
    if(kind==='docker'){
     output('容器实时日志','正在连接日志流…');const source=new EventSource('/api/docker/'+id+'/logs?follow=true');stream=source;let first=true;
     source.onmessage=e=>{if(stream!==source)return;if(first){$('#output').textContent='';first=false}$('#output').textContent=($('#output').textContent+JSON.parse(e.data)).slice(-65536);$('#output').scrollTop=$('#output').scrollHeight};
     source.onerror=()=>{source.close();if(stream===source)$('#output').textContent+='\n[日志连接结束；关闭后可重新打开]'};
    }else output('任务日志',(await api('/tasks/'+id+'/logs')).output);
    return;
   }
   await api('/'+kind+'/'+encodeURIComponent(id),{action,confirm:id,name});notify((labels[action]||'操作')+'已完成');if(kind==='zellij'&&action==='rename')localStorage.setItem('orh-session',name);await refresh();
  }catch(e){showError(e)}
 });
}
async function refresh(){
 if($('#shell').hidden)return;
 if(busy){refreshQueued=true;return}
 const version=++renderVersion,target=view;busy=true;$('#refresh').disabled=true;
 try{if($('#error').dataset.kind!=='operation')$('#error').hidden=true;await ({overview,proxy:v=>RemoteHubProxy.render(()=>v===renderVersion),docker:dockerView,zellij:zellijView,tasks:tasksView,dsh:v=>RemoteHubDsh.render(()=>v===renderVersion),files:v=>RemoteHubWorkspace.files(()=>v===renderVersion),projects:v=>RemoteHubWorkspace.projects(()=>v===renderVersion),environments:v=>RemoteHubWorkspace.environments(()=>v===renderVersion)}[target])(version);if(version===renderVersion)$('#connection').textContent='已连接'}
 catch(e){if(version===renderVersion){if($('#content').textContent==='正在读取本机数据…')$('#content').innerHTML=empty('暂时无法读取，请点击刷新重试。');showError(e.name==='TimeoutError'?Error('读取超时，请稍后刷新。现有任务不会因此停止。'):e,false)}}
 finally{if(version===renderVersion){busy=false;$('#refresh').disabled=false;if(refreshQueued){refreshQueued=false;queueMicrotask(refresh)}}}
}
let needsSetup=false;
async function loadAuth(){try{const status=await api('/auth/status');needsSetup=status.needs_setup;$('#setupConfirm').hidden=!needsSetup;$('#passwordConfirm').required=needsSetup;$('#password').autocomplete=needsSetup?'new-password':'current-password';$('#password').minLength=needsSetup?10:0;$('#passwordLabel').textContent=needsSetup?'设置登录密码（至少 10 个字符）':'登录密码';$('#loginSubmit').textContent=needsSetup?'设置密码并进入 →':'进入控制台 →';$('#loginHelp').textContent=needsSetup?'首次使用，请在本机设置你自己的密码。密码仅保存为加盐哈希。':'使用自设密码登录。登录后进入终端无需再次认证。'}catch(e){$('#loginError').textContent=e.message}}
async function enter(){try{if((await api('/auth/status')).needs_setup){showLogin();await loadAuth();return}me=await api('/me');$('#role').textContent=me.role==='admin'?'管理员':'只读';$('#login').hidden=true;$('#shell').hidden=false;switchView(view)}catch(e){if(!$('#login').hidden)$('#loginError').textContent=e.message;else showError(e)}}
$('#loginForm').onsubmit=async e=>{e.preventDefault();const button=$('#loginSubmit');button.disabled=true;try{if(needsSetup&&$('#password').value!==$('#passwordConfirm').value)throw Error('两次输入的密码不一致');await api(needsSetup?'/auth/setup':'/login',{password:$('#password').value});$('#loginForm').reset();$('#loginError').textContent='';needsSetup=false;await enter()}catch(e){$('#loginError').textContent=e.message;await loadAuth()}finally{button.disabled=false}};
$('#changePassword').onclick=()=>{$('#passwordForm').reset();$('#passwordError').textContent='';$('#passwordDialog').showModal()};$('#cancelPassword').onclick=()=>$('#passwordDialog').close();$('#passwordForm').onsubmit=async e=>{e.preventDefault();try{if($('#newPassword').value!==$('#newPasswordConfirm').value)throw Error('两次输入的新密码不一致');await api('/auth/password',{current_password:$('#currentPassword').value,password:$('#newPassword').value});$('#passwordForm').reset();$('#passwordDialog').close();notify('密码已更新，其他登录已失效')}catch(e){$('#passwordError').textContent=e.message}};
document.querySelectorAll('nav button').forEach(b=>b.onclick=()=>{if(b.dataset.view!==view)switchView(b.dataset.view)});
$('#content').onclick=e=>{const b=e.target.closest('button[data-kind]');if(b)act(b.dataset.kind,b.dataset.id,b.dataset.action,b)};
$('#refresh').onclick=refresh;$('#theme').onclick=()=>{document.body.classList.toggle('dark');localStorage.setItem('orh-theme',document.body.classList.contains('dark')?'dark':'light');updateThemeControl()};$('#logout').onclick=async()=>{try{await api('/logout',{});showLogin()}catch(e){showError(e)}};$('#closeOutput').onclick=()=>$('#outputDialog').close();$('#outputDialog').onclose=()=>{if(stream){stream.close();stream=null}};$('#cancelTask').onclick=()=>$('#taskDialog').close();$('#taskForm').onsubmit=async e=>{
 e.preventDefault();const start=e.submitter?.value==='run',button=e.submitter;
 await withBusy(button,'task:new',start?'保存并启动中…':'保存中…',async()=>{
  try{
   const input=$('#taskArgv').value.trim();let command;if(input.startsWith('[')){const argv=JSON.parse(input);if(!Array.isArray(argv)||!argv.length||!argv.every(x=>typeof x==='string'))throw Error('请输入有效命令或非空字符串数组');command={argv}}else command={command:input};
   const cwd=$('#taskCwd').value;const d=await api('/tasks',{name:$('#taskName').value,...command,cwd});localStorage.setItem('orh-task-cwd',cwd);
   $('#taskDialog').close();$('#taskForm').reset();
   if(start){try{await api('/tasks/'+d.id,{action:'start',confirm:d.id});notify('任务已启动')}catch(e){showError(Error('任务已保存，但启动失败：'+e.message));await refresh();return}}
   else notify('任务已保存');
   await refresh();
  }catch(e){$('#taskError').textContent=e.message}
 });
};
setInterval(()=>{if(!['files','projects','environments','dsh','proxy'].includes(view)&&!document.hidden&&!pendingOperations.size&&!$('#nameDialog').open&&!$('#sessionDialog').open&&!$('#passwordDialog').open&&!$('#outputDialog').open&&!$('#taskDialog').open&&!$('#confirmDialog').open)refresh()},5000);

document.addEventListener('visibilitychange',()=>{if(!document.hidden&&!pendingOperations.size&&!['files','environments','dsh','proxy'].includes(view)&&!$('#workspaceDialog').open&&!$('#workspaceDetailDialog').open)refresh()});
$('#cancelName').onclick=()=>$('#nameDialog').close('cancel');
$('#cancelSession').onclick=()=>$('#sessionDialog').close();$('#sessionForm').onsubmit=e=>{e.preventDefault();const name=$('#sessionName').value.trim();if(!/^[A-Za-z0-9][A-Za-z0-9_.-]*$/.test(name)){$('#sessionError').textContent='名称仅支持字母、数字、点、下划线、短横线';return}if(mountTerminal(name))$('#sessionDialog').close()};

function updateThemeControl(){const dark=document.body.classList.contains('dark'),label=dark?'切换为浅色模式':'切换为暗色模式';$('#theme').setAttribute('aria-label',label);$('#theme').setAttribute('title',label);$('#themeMoon').hidden=dark;$('#themeSun').hidden=!dark}
updateThemeControl();
window.addEventListener?.('beforeunload',e=>{if(window.RemoteHubWorkspace?.isDirty()||window.RemoteHubProxyManager?.isDirty()){e.preventDefault();e.returnValue=''}});
enter();
