'use strict';
const $=s=>document.querySelector(s), esc=s=>String(s??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const bytes=n=>{n=Number(n);if(!Number.isFinite(n))return '—';const units=['B','KB','MB','GB','TB'];let i=0;while(n>=1024&&i<4){n/=1024;i++}return `${n.toFixed(i?1:0)} ${units[i]}`};
const uptime=s=>{s=Math.max(0,s);return `${Math.floor(s/86400)} 天 ${Math.floor(s%86400/3600)} 小时`};
let renderVersion=0;
let caps={};let view=typeof location!=='undefined'&&['#overview','#modules','#proxy','#remote','#lan','#nodebaby','#network','#mesh','#settings','#desktop'].includes(location.hash)?location.hash.slice(1):localStorage.getItem('orh-view')||'overview', me, busy=false, stream, chartHours=1,refreshQueued=false;
const pendingOperations=new Set();
const titles={modules:'功能管理',remote:'本地局域网',lan:'本地局域网',nodebaby:'节点小宝',knowledge:'知识库',ssh:'SSH 管理',proxy:'网络代理',overview:'系统概览',docker:'容器与镜像',zellij:'终端管理',files:'文件管理',projects:'项目管理',environments:'开发环境',dsh:'DeepSeek Harness',services:'进程与服务',meshremote:'组网状态',mesh:'组网状态',settings:'设备访问设置',desktop:'远程桌面',applications:'我的应用'};
let sidebarCollapsed=localStorage.getItem('orh-sidebar-collapsed')==='true';
function updateSidebar(){
 document.body.classList.toggle('sidebar-collapsed',sidebarCollapsed);
 const button=$('#sidebarToggle'),label=sidebarCollapsed?'展开导航':'收起导航';
 button.setAttribute('aria-expanded',String(!sidebarCollapsed));button.setAttribute('aria-label',label);button.title=label;
 document.querySelectorAll('aside nav button').forEach(item=>{const name=item.textContent.trim();item.title=name;item.setAttribute('aria-label',name)});
}
updateSidebar();
$('#sidebarToggle').onclick=()=>{sidebarCollapsed=!sidebarCollapsed;localStorage.setItem('orh-sidebar-collapsed',String(sidebarCollapsed));updateSidebar()};
if(['network','meshremote'].includes(view))view='mesh';
if(view==='remote')view='lan';
if(view==='tasks')view='services';
const clientTheme=typeof location==='undefined'?null:new URLSearchParams(location.search).get('client_theme');
if(['light','dark'].includes(clientTheme))localStorage.setItem('orh-theme',clientTheme);
if(localStorage.getItem('orh-theme')==='dark'||(!localStorage.getItem('orh-theme')&&matchMedia('(prefers-color-scheme: dark)').matches))document.body.classList.add('dark');
async function api(path,body){const r=await fetch('/api'+path,{method:body===undefined?'GET':'POST',headers:body===undefined?{}:{'Content-Type':'application/json','X-ORH-Request':'1'},body:body===undefined?undefined:JSON.stringify(body),signal:AbortSignal.timeout(body===undefined?((path.startsWith('/environments')||path.startsWith('/local-services')||path.startsWith('/remote-connect'))?30000:10000):(path.startsWith('/proxy/manager')?90000:60000))});let d;try{d=await r.json()}catch{throw Error('服务器返回异常响应')}if(r.status===401){showLogin();throw Error(d.detail||'请重新登录')}if(!r.ok){const error=Error(typeof d.detail==='string'?d.detail:d.detail?.message||JSON.stringify(d.detail));error.status=r.status;throw error}return d}
async function copyText(value) {
 if(navigator.clipboard&&window.isSecureContext)return navigator.clipboard.writeText(value);
 const input=document.createElement('textarea');input.value=value;input.setAttribute('readonly','');document.body.append(input);input.select();
 const copied=document.execCommand('copy');input.remove();if(!copied)throw Error('复制未成功，请手动选中内容复制');
}
async function withBusy(button,key,label,work){
 if(pendingOperations.has(key))return;pendingOperations.add(key);
 const text=button?.textContent,markup=button?.innerHTML;
 if(button){button.disabled=true;button.textContent=label;button.setAttribute('aria-busy','true')}
 try{return await work()}finally{pendingOperations.delete(key);if(button?.isConnected){button.disabled=false;if(markup!==undefined)button.innerHTML=markup;else button.textContent=text;button.removeAttribute('aria-busy')}}
}
const VIEW_CAP={docker:'docker',zellij:'terminal',files:'files',ssh:'ssh',dsh:'dsh',services:'services',projects:'projects',environments:'environments',knowledge:'knowledge',desktop:'desktop',lan:'lan',nodebaby:'nodebaby',proxy:'proxy',applications:'services'};
function updateNavigation(){
 document.querySelectorAll('aside nav [data-view]').forEach(button=>{
  const requirement=VIEW_CAP[button.dataset.view];
  button.hidden=Boolean(requirement&&(caps.enabled_modules ? !caps.enabled_modules.includes(requirement) : caps[requirement]===false));
 });
}
async function switchView(target){
 if(['network','meshremote'].includes(target))target='mesh';
 if(target==='remote')target='lan';
 if(view!==target&&window.RemoteHubMesh&&!await RemoteHubMesh.canLeave())return;
 if(view!==target&&window.RemoteHubAgentSettings&&!await RemoteHubAgentSettings.canLeave())return;
 if(VIEW_CAP[target]&&caps[VIEW_CAP[target]]===false&&!(target==='proxy'&&caps.enabled_modules?.includes('proxy'))){notify('请在功能管理中启用或检查依赖');target='modules'}
 document.body.dataset.module=target;
 document.body.dataset.platform=me?.host?.system==='Windows'?'windows':'unix';
 if(target==='tasks')target='services';
 if(view!==target&&window.RemoteHubRemoteConnect&&!await RemoteHubRemoteConnect.canLeave())return;
 if(view!==target&&window.RemoteHubApplications&&!RemoteHubApplications.canLeave())return;
 if(view!==target&&window.RemoteHubSSH&&!await RemoteHubSSH.canLeave())return;
 if(view!==target&&window.RemoteHubProxyManager&&!await RemoteHubProxyManager.canLeave())return;
 if(view!==target&&window.RemoteHubKnowledge&&!await RemoteHubKnowledge.canLeave())return;
 if(view!==target&&window.RemoteHubWorkspace&&!await RemoteHubWorkspace.canLeave())return;
 if(!titles[target])target='overview';
 if(target!==view)window.scrollTo?.(0,0);
 renderVersion++;busy=false;window.RemoteHubSessions?.close();view=target;localStorage.setItem('orh-view',view);
 document.querySelectorAll('nav button').forEach(x=>x.classList.toggle('active',x.dataset.view===view));
 $('#title').textContent=titles[view];$('#breadcrumb').textContent=(me?.host?.hostname||'设备控制台')+' / '+titles[view];
 $('#error').hidden=true;$('#content').innerHTML=empty('正在读取本机数据…');refresh();
}
function showLogin(){window.dispatchEvent?.(new CustomEvent('orh:login-required'));window.RemoteHubRemoteConnect?.reset();window.RemoteHubLAN?.reset();window.RemoteHubNodeBaby?.reset();window.RemoteHubApplications?.reset();window.RemoteHubLocalServices?.reset();window.RemoteHubKnowledge?.reset();window.RemoteHubAgentSettings?.reset();window.RemoteHubMesh?.reset();window.RemoteHubSSH?.reset();window.RemoteHubWorkspace?.reset();renderVersion++;busy=false;window.RemoteHubSessions?.close();$('#login').hidden=false;$('#shell').hidden=true;if(stream)stream.close();$('#content').replaceChildren();loadAuth()}
function notify(text){$('#toast').textContent=text;$('#toast').hidden=false;setTimeout(()=>$('#toast').hidden=true,3500)}
function showError(e,operation=true){$('#error').textContent=e.message;$('#error').dataset.kind=operation?'operation':'load';$('#error').hidden=false;if(!operation)$('#connection').textContent='更新失败 · 保留最近数据'}
async function confirmAction(title,message){if($('#confirmDialog').open)return false;$('#confirmTitle').textContent=title;$('#confirmMessage').textContent=message;$('#confirmDialog').returnValue='cancel';$('#confirmDialog').showModal();return new Promise(resolve=>$('#confirmDialog').addEventListener('close',()=>resolve($('#confirmDialog').returnValue==='confirm'),{once:true}))}
function requestName(title,value='',submit='保存',limit=80,allowEmpty=false){
 const dialog=$('#nameDialog');if(dialog.open)return Promise.resolve(null);
 $('#nameTitle').textContent=title;$('#nameInput').value=value;$('#nameInput').maxLength=limit;$('#nameInput').required=!allowEmpty;$('#saveName').textContent=submit;dialog.returnValue='cancel';dialog.showModal();$('#nameInput').focus();$('#nameInput').select();
 return new Promise(resolve=>{dialog.onclose=()=>resolve(dialog.returnValue==='save'?$('#nameInput').value.trim():null);$('#nameForm').onsubmit=e=>{e.preventDefault();if(allowEmpty||$('#nameInput').value.trim())dialog.close('save')}});
}
function output(title,text){$('#output').dataset.format='text';if(stream){stream.close();stream=null}$('#outputTitle').textContent=title;$('#output').textContent=text;$('#outputDialog').showModal()}
function panel(title,body,extra='',desc=''){return `<section class="panel"><div class="panel-head"><div><h2>${title}</h2>${desc?`<p>${desc}</p>`:''}</div>${extra}</div>${body}</section>`}
function table(head,rows){return `<div class="table-wrap"><table><thead><tr>${head.map(x=>`<th>${x}</th>`).join('')}</tr></thead><tbody>${rows.join('')}</tbody></table></div>`}
function empty(text){return `<div class="empty">${text}</div>`}
function badge(state){return `<span class="badge ${['running','exited'].includes(state)?state:''}">${esc(state)}</span>`}
function buttons(kind,id,actions){if(me.role!=='admin')return '<small>只读</small>';return actions.map(([action,label])=>`<button data-kind="${kind}" data-id="${esc(id)}" data-action="${action}" ${['stop','kill','delete'].includes(action)?'class="danger"':''}>${icon({start:'start',stop:'stop',restart:'refresh',delete:'delete',kill:'stop'}[action])}${label}</button>`).join('')}
function procTable(list){return table(['进程 / 命令','PID','CPU¹','内存','运行时间'],list.map(p=>`<tr><td class="command" title="${esc(p.command)}"><strong>${esc(p.name)}</strong><br><small class="mono">${esc(p.command)}</small></td><td class="mono">${p.pid}</td><td class="mono">${p.cpu.toFixed(1)}%</td><td class="mono">${bytes(p.memory)}</td><td>${uptime(Date.now()/1000-p.created)}</td></tr>`))}
function chart(data){if(data.length<2)return empty('正在采集真实数据，稍候即可查看趋势。');const w=900,h=170,left=34,right=12,top=15,bottom=28,start=data[0].time,end=data.at(-1).time;const x=t=>left+(t-start)/(end-start)*(w-left-right),y=v=>h-bottom-v/100*(h-top-bottom);const path=k=>data.map((p,i)=>`${i?'L':'M'}${x(p.time).toFixed(1)},${y(p[k]).toFixed(1)}`).join(' ');return `<svg class="chart" viewBox="0 0 ${w} ${h}" preserveAspectRatio="none" role="img" aria-label="CPU 与内存历史使用率">${[0,25,50,75,100].map(v=>`<line class="grid" x1="${left}" x2="${w-right}" y1="${y(v)}" y2="${y(v)}"/><text x="0" y="${y(v)+3}">${v}%</text>`).join('')}<path class="mem" d="${path('memory')}"/><path class="cpu" d="${path('cpu')}"/>${[0,.25,.5,.75,1].map(f=>`<text x="${left+f*(w-left-right)}" y="${h-4}" text-anchor="${f===0?'start':f===1?'end':'middle'}">${new Date((start+(end-start)*f)*1000).toLocaleTimeString('zh-CN',{hour:'2-digit',minute:'2-digit'})}</text>`).join('')}</svg>`}
async function overview(version){
 const d=await api('/system');
 if(version!==renderVersion)return;
 const m=d.metrics,host=d.host;
 if(!m){$('#content').innerHTML=empty('正在进行首次系统采样…');return}

 const cards=[
  ['CPU 使用率',m.cpu.toFixed(1),'%',`${host.cores} 个逻辑核心`,m.cpu,'cpu'],
  ...(d.gpu?[['GPU',d.gpu.name,'',[d.gpu.util!=null?d.gpu.util+'% 使用率':'',d.gpu.cores?d.gpu.cores+' 核':'',d.gpu.vram||''].filter(Boolean).join(' · '),null,'activity']]:[]),
  ['内存使用率',m.memory.toFixed(1),'%',`${bytes(m.memory_used)} / ${bytes(m.memory_total)}`,m.memory,'memory'],
  ['磁盘使用率',m.disk.toFixed(1),'%',`${bytes(m.disk_used)} / ${bytes(m.disk_total)}`,m.disk,'disk']
 ];
 const metric=([label,n,unit,detail,pct,ic])=>`<div class="metric"><div class="metric-label">${label}<span>${icon(ic)}</span></div><div class="metric-value"${unit?'':' style="font-size:18px"'}>${n}${unit?' <small>'+unit+'</small>':''}</div>${pct==null?'':`<div class="meter"><i style="width:${Math.min(100,pct)}%"></i></div>`}<small>${detail}</small></div>`;
 const info=(title,value,detail)=>`<div class="metric"><div class="metric-label">${title}<span>${icon('network')}</span></div><div class="metric-value" style="font-size:20px">${value}</div><small>${detail}</small></div>`;
 $('#content').innerHTML=`<div class="host-strip"><span class="host-icon">${icon('server')}</span><div><strong>${esc(host.hostname)}</strong><small>${esc(host.system)} ${esc(host.version)} · ${esc(host.arch)} · ${host.cores} 核 CPU</small></div><div class="host-meta">${badge('running')}<br>已运行 ${uptime(Date.now()/1000-host.boot)}</div></div><div class="metrics">${cards.map(metric).join('')}</div><h2 class="section-title">网络</h2><div class="metrics">${info('网络吞吐',bytes(m.rx)+'/s','↑ '+bytes(m.tx)+'/s · ↓ 接收')}</div>`;
 $('#updated').textContent='采样于 '+new Date(m.time*1000).toLocaleTimeString();
 if(d.error)throw Error(d.error);
}
async function dockerView(version){const d=await api('/docker');if(version!==renderVersion)return;$('#content').innerHTML=panel('容器',d.containers.length?`<div class="container-grid">${d.containers.map(c=>{const s=d.stats.find(x=>x.ID===c.ID||c.ID.startsWith(x.ID)||x.Name===c.Names);return `<article class="container-card"><div class="container-heading"><h3 class="mono">${esc(c.Names)}</h3>${badge(c.State)}</div><p class="container-image mono">${esc(c.Image)}</p><p class="muted">${esc(c.Status)}</p><dl class="container-stats"><div><dt>CPU</dt><dd>${s?esc(s.CPUPerc):'—'}</dd></div><div><dt>内存</dt><dd>${s?esc(s.MemUsage):'—'}</dd></div></dl><div class="container-ports"><small>${c.State==='running'?'端口映射':'配置端口（未监听）'}</small><p class="mono">${esc(c.Ports||c.ConfiguredPorts)||'无映射'}</p></div><div class="toolbar">${buttons('docker',c.ID,c.State==='running'?[['stop','停止'],['restart','重启']]:[['start','启动']])}<button data-kind="docker" data-id="${c.ID}" data-action="detail" aria-label="${esc(c.Names)} 详情">详情</button><button data-kind="docker" data-id="${c.ID}" data-action="logs" aria-label="${esc(c.Names)} 日志">日志</button></div></article>`}).join('')}</div>`:empty('Docker 当前没有容器。'),`<span class="badge">${d.containers.length} 个容器</span>`,'资源占用来自 Docker 实时统计；停止的容器显示为空。')+panel('本地镜像',d.images.length?table(['镜像仓库','标签','大小','创建时间'],d.images.map(i=>`<tr><td class="mono">${esc(i.Repository)}</td><td>${esc(i.Tag)}</td><td>${esc(i.Size)}</td><td>${esc(i.CreatedSince)}</td></tr>`)):empty('暂无镜像'));}
async function zellijView(version){return RemoteHubSessions.render(me,api,()=>version===renderVersion)}
function mountTerminal(name){
 if(window.ORHClientWorkspace?.openTerminal('/terminal/open/'+encodeURIComponent(name)))return true;
 const url='/terminal/open/'+encodeURIComponent(name),tab=window.open(url,'_blank');
 if(tab){tab.opener=null;return true}
 $('#error').replaceChildren(document.createTextNode('浏览器阻止了新标签页。'));
 const link=document.createElement('a');link.href=url;link.target='_blank';link.rel='noopener';link.textContent='点击这里进入终端 ↗';$('#error').append(link);$('#error').hidden=false;return false;
}

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
   if(action==='detail'){const value=await api('/'+kind+'/'+encodeURIComponent(id));$('#outputTitle').textContent=kind==='services'?'服务进程与日志':'容器详情';$('#output').dataset.format='structured';$('#output').innerHTML=RemoteHubFormControls.facts(value);$('#outputDialog').showModal();return}
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
async function refresh(force=false){
 if($('#shell').hidden)return;
 if(busy){refreshQueued=true;return}
 const version=++renderVersion,target=view;busy=true;$('#refresh').disabled=true;
 try{if($('#error').dataset.kind!=='operation')$('#error').hidden=true;await ({overview,modules:v=>RemoteHubModules.render(()=>v===renderVersion),lan:v=>RemoteHubLAN.render(()=>v===renderVersion),nodebaby:v=>RemoteHubNodeBaby.render(()=>v===renderVersion),desktop:v=>RemoteHubRemoteConnect.render(()=>v===renderVersion),mesh:v=>RemoteHubMesh.render(()=>v===renderVersion,'#content',api),settings:v=>RemoteHubAgentSettings.render(()=>v===renderVersion,'#content',api),knowledge:v=>RemoteHubKnowledge.render(()=>v===renderVersion),ssh:v=>RemoteHubSSH.render(()=>v===renderVersion),proxy:v=>RemoteHubProxy.render(()=>v===renderVersion),docker:dockerView,zellij:zellijView,applications:v=>RemoteHubApplications.render(()=>v===renderVersion),services:v=>RemoteHubLocalServices.render(()=>v===renderVersion,force),dsh:v=>RemoteHubDsh.render(()=>v===renderVersion),files:v=>RemoteHubWorkspace.files(()=>v===renderVersion),projects:v=>RemoteHubWorkspace.projects(()=>v===renderVersion),environments:v=>RemoteHubWorkspace.environments(()=>v===renderVersion)}[target])(version);if(version===renderVersion)$('#connection').textContent='已连接'}
 catch(e){if(version===renderVersion){if($('#content').textContent==='正在读取本机数据…')$('#content').innerHTML=empty('暂时无法读取，请点击刷新重试。');showError(e.name==='TimeoutError'?Error('读取超时，请稍后刷新。现有任务不会因此停止。'):e,false)}}
 finally{if(version===renderVersion){busy=false;$('#refresh').disabled=false;if(refreshQueued){refreshQueued=false;queueMicrotask(refresh)}}}
}
async function loadAuth() {
 try {
  const status = await api('/auth/status');
  const bound = Boolean(status.cloud?.bound);
  $('#cloudRegister').href = (status.cloud?.cloud_url || $('#cloudServer').value).replace(/\/+$/, '') + '/#register';
  $('#cloudLogin').hidden = !bound;
  $('#cloudBlock').hidden = bound;
  $('#localRecovery').hidden = !(status.recovery_enabled || (!bound && (status.local_password_set || status.needs_setup)));
  $('#localLogin').dataset.setup = String(status.needs_setup);
  $('#localLogin').textContent = status.needs_setup ? '设置本地密码并登录' : '本地登录';
  if (bound) $('#loginHelp').textContent = '此设备使用已绑定的 ORH 账号登录。';
  else $('#loginHelp').textContent = '使用 ORH 账号登录，本机会自动注册并接入组网。';
 } catch (error) {$('#loginError').textContent=error.message;}
}
async function enter() {
 try {
  me = await api('/me');
  caps = await api('/capabilities').catch(() => ({}));
  window.ORH_CAPS = caps;
  updateNavigation();
  $('#role').textContent = me.role === 'admin' ? '管理员' : '只读';
  $('#cloudBind').hidden = Boolean(me.cloud?.bound);
  $('#login').hidden = true;
  $('#shell').hidden = false;
  window.dispatchEvent?.(new CustomEvent('orh:authenticated', {detail:me}));
  const portal = $('#portalLink');
  portal.href = (me.cloud?.base_url || 'https://cloud.openremotehub.top') + '/'; portal.title='打开 Cloud 门户';
  
  switchView(view);
 } catch (error) {
  if (!$('#login').hidden) $('#loginError').textContent = error.message;
  else showError(error);
 }
}
$('#cloudLoginSubmit').onclick = async () => {
 const button = $('#cloudLoginSubmit');
 button.disabled = true; $('#loginError').textContent = '';
 try {
  await api('/auth/cloud/login',{cloud_url:$('#cloudServer').value.trim(),
   username:$('#cloudUser').value.trim(),password:$('#cloudPassword').value});
  $('#cloudPassword').value = '';
  await enter();
 } catch (error) {$('#loginError').textContent = error.message;}
 finally {button.disabled = false;}
};
$('#localPassword').onkeydown=event=>{if(event.key==='Enter'){event.preventDefault();$('#localLogin').click()}};
$('#localLogin').onclick=async()=>{try{await api($('#localLogin').dataset.setup==='true'?'/auth/setup':'/login',{password:$('#localPassword').value});$('#localPassword').value='';await enter()}catch(error){$('#loginError').textContent=error.message}};
$('#loginForm').onsubmit=event=>{event.preventDefault();if(!$('#cloudBlock').hidden)$('#cloudLoginSubmit').click()};

$('#cloudBind').onclick = async () => {
 $('#cloudBindDialog').showModal();
 $('#agentBindError').textContent = '';
 syncCloudRegister();
};
function syncCloudRegister(){
 const base=($('#agentCloudURL').value||'').trim().replace(/\/$/,'');
 $('#agentCloudRegister').href=base?base+'/':'#';
}
$('#agentCloudURL').oninput = syncCloudRegister;
$('#agentBindClose').onclick = () => $('#cloudBindDialog').close();
$('#cloudBindForm').onsubmit = async event => {
 event.preventDefault();
 const button=$('#agentBindSubmit');
 button.disabled=true; $('#agentBindError').textContent='';
 try {
  await api('/cloud/login',{cloud_url:$('#agentCloudURL').value.trim(),
    username:$('#agentCloudUser').value.trim(),password:$('#agentCloudPassword').value});
  $('#cloudBindDialog').close();
  location.reload();
 } catch (error) {$('#agentBindError').textContent=error.message;}
 finally {button.disabled=false;}
};

document.querySelectorAll('nav button[data-view]').forEach(b=>b.onclick=()=>{if(b.dataset.view!==view)switchView(b.dataset.view)});document.querySelectorAll('button[data-client-page]').forEach(b=>b.onclick=()=>{if(window.ORHClientWorkspace)ORHClientWorkspace.openClientPage(b.dataset.clientPage);else location.assign('/client#'+b.dataset.clientPage)});$('#content').addEventListener('click',e=>{const card=e.target.closest('[data-open-view]');if(card&&card.dataset.openView!==view)switchView(card.dataset.openView)});
$('#content').onclick=e=>{const b=e.target.closest('button[data-kind]');if(b)act(b.dataset.kind,b.dataset.id,b.dataset.action,b)};
$('#refresh').onclick=()=>refresh(true);$('#theme').onclick=()=>{document.body.classList.toggle('dark');localStorage.setItem('orh-theme',document.body.classList.contains('dark')?'dark':'light');updateThemeControl()};$('#logout').onclick=async()=>{try{await api('/logout',{});showLogin()}catch(e){showError(e)}};$('#closeOutput').onclick=()=>$('#outputDialog').close();$('#outputDialog').onclose=()=>{if(stream){stream.close();stream=null}};
setInterval(()=>{if(!['modules','files','projects','environments','dsh','proxy','ssh','knowledge','applications','remote','settings','mesh','desktop'].includes(view)&&!document.hidden&&!pendingOperations.size&&!$('#nameDialog').open&&!$('#sessionDialog').open&&!$('#outputDialog').open&&!window.RemoteHubApplications?.isOpen()&&!window.RemoteHubLocalServices?.isOpen()&&!(view==='services'&&document.activeElement?.closest('.service-toolbar'))&&!$('#confirmDialog').open)refresh()},5000);

document.addEventListener('visibilitychange',()=>{if(!document.hidden&&!pendingOperations.size&&!['files','environments','dsh','proxy','ssh','knowledge','applications','remote','settings','mesh','desktop'].includes(view)&&!$('#workspaceDialog').open&&!$('#workspaceDetailDialog').open)refresh()});
$('#cancelName').onclick=()=>$('#nameDialog').close('cancel');
$('#cancelSession').onclick=()=>$('#sessionDialog').close();$('#sessionForm').onsubmit=e=>{e.preventDefault();const name=$('#sessionName').value.trim();if(!/^[A-Za-z0-9][A-Za-z0-9_.-]*$/.test(name)){$('#sessionError').textContent='名称仅支持字母、数字、点、下划线、短横线';return}if(mountTerminal(name))$('#sessionDialog').close()};

function updateThemeControl(){const dark=document.body.classList.contains('dark'),label=dark?'切换为浅色模式':'切换为暗色模式';$('#theme').setAttribute('aria-label',label);$('#theme').setAttribute('title',label);$('#themeMoon').hidden=dark;$('#themeSun').hidden=!dark}
updateThemeControl();
window.addEventListener?.('beforeunload',e=>{if(window.RemoteHubSSH?.isDirty()||window.RemoteHubWorkspace?.isDirty()||window.RemoteHubProxyManager?.isDirty()){e.preventDefault();e.returnValue=''}});
enter();

window.addEventListener?.('hashchange',async()=>{
 const target={'#network':'mesh','#remote':'lan'}[location.hash]||location.hash.slice(1);
 if(!titles[target]||$('#shell').hidden)return;
 await switchView(target);
});

$('#cloudRegister').onclick = () => { if (!$('#cloudBlock').hidden) $('#cloudRegister').href = $('#cloudServer').value.trim().replace(/\/+$/, '') + '/#register'; };
