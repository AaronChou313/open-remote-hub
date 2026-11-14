const $ = selector => document.querySelector(selector);
const escapeHTML = value => String(value ?? '').replace(/[&<>"']/g, char => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[char]));
const fragment = new URLSearchParams(location.hash.slice(1));
if (fragment.has('token')) {localStorage.setItem('orn-api-token',fragment.get('token'));history.replaceState(null,'',location.pathname);}
let token = localStorage.getItem('orn-api-token') || '';
let peers = [];
let selected;
let connecting = false;
let busy = false;
let sharedWithORH=false;
let cloudError="";
const latency = new Map();
function theme(dark) {document.documentElement.classList.toggle('dark',dark);$('#theme').textContent=dark?'☀':'☾';localStorage.setItem('orn-theme',dark?'dark':'light');}
theme(localStorage.getItem('orn-theme') === 'dark' || !localStorage.getItem('orn-theme') && matchMedia('(prefers-color-scheme:dark)').matches);
$('#theme').onclick=()=>theme(!document.documentElement.classList.contains('dark'));
function notice(text,error=false) {$('#notice').textContent=text;$('#notice').hidden=!text;$('#notice').classList.toggle('error',error);}
async function api(path,body,method=body===undefined?'GET':'POST') {
 const response=await fetch('/api/v1'+path,{method,headers:{Authorization:'Bearer '+token,'Content-Type':'application/json'},body:body===undefined?undefined:JSON.stringify(body),signal:AbortSignal.timeout(16000)});
 const result=await response.json();
 if(response.status===401) $('#tokenPanel').hidden=false;
 if(!response.ok) throw Error(result.detail || '操作未完成');
 return result;
}
async function action(button,work) {
 if(busy) return;
 busy=true;button.disabled=true;
 try {await work();} catch(error) {notice(error.message,true);} finally {busy=false;if(button.isConnected)button.disabled=false;}
}
async function refresh() {
 const [status,devices,forwards]=await Promise.all([api('/status'),api('/peers'),api('/forwards')]);
 $('#tokenPanel').hidden=true;
 const running=status.backend_state==='Running';
 $('#self').innerHTML=`<div><h2>${escapeHTML(status.device.hostname || '此设备')}</h2><span class="muted">${escapeHTML(status.device.ips.join(' · ') || status.backend_state)}</span></div><span class="state ${running?'online':''}">${running?'已连接':escapeHTML(status.backend_state)}</span>`;
 sharedWithORH=Boolean(status.cloud?.shared_with_orh);
 const nextError=status.cloud?.error || '';
 if(nextError) notice('Cloud · '+nextError,true);
 else if(cloudError) notice('');
 cloudError=nextError;
 $('#binding').hidden=Boolean(status.cloud?.bound);
 $('#bindingCode').innerHTML='';
 if(status.cloud?.error) $('#bindingCode').textContent=status.cloud.error;
 if(status.cloud?.pending) $('#bindingCode').innerHTML=`<p>绑定码 <strong>${escapeHTML(status.cloud.pending.user_code)}</strong></p><a href="${escapeHTML(status.cloud.pending.verification_url)}" target="_blank" rel="noopener">前往 Cloud 确认绑定 ↗</a>`;
 peers=devices;renderPeers();
 $('#forwards').innerHTML=forwards.map(row=>`<div class="forward-row"><div><p>127.0.0.1:${row.local_port} → ${escapeHTML(row.peer_ip)}:${row.remote_port}</p><small>${row.connections} 个活动连接</small></div><button data-close="${escapeHTML(row.id)}">关闭转发</button></div>`).join('') || '<p class="empty">连接设备时会自动建立转发。</p>';
 document.querySelectorAll('[data-close]').forEach(button=>button.onclick=()=>action(button,async()=>{await api('/forwards/'+button.dataset.close,undefined,'DELETE');await refresh();}));
}
function renderPeers() {
 const query=$('#search').value.toLowerCase();
 $('#devices').innerHTML=peers.filter(peer=>(peer.hostname+' '+peer.ips.join(' ')).toLowerCase().includes(query)).map(peer=>`<article class="peer"><div class="peer-main"><h3>${escapeHTML(peer.hostname)}</h3><p>${escapeHTML(peer.ips.join(' · '))}</p><small class="${peer.online?'online':''}">${peer.online?'在线':'离线'} · ${escapeHTML(peer.os)}</small></div><div class="path"><strong>${peer.path==='direct'?'直连':peer.path==='relay'?'中继':'待连接'}</strong><br>${latency.has(peer.id)?escapeHTML(latency.get(peer.id)):escapeHTML(peer.path==='relay'?peer.relay:'')}</div><div class="actions"><button data-ping="${escapeHTML(peer.id)}">检测</button><button data-forward="${escapeHTML(peer.id)}">端口转发</button><button data-console="${escapeHTML(peer.id)}">控制台</button><button class="primary" data-connect="${escapeHTML(peer.id)}" ${peer.online?'':'disabled'}>远程桌面</button></div></article>`).join('') || '<p class="empty">暂无匹配的设备。将其他设备绑定到相同账号后显示在这里。</p>';
 document.querySelectorAll('[data-ping]').forEach(button=>button.onclick=()=>action(button,async()=>{const peer=peers.find(p=>p.id===button.dataset.ping);const result=await api('/ping',{peer_ip:peer.ips[0]});latency.set(peer.id,result.Err || Math.round(result.LatencySeconds*1000)+' ms');await refresh();}));
 document.querySelectorAll('[data-console]').forEach(button=>button.onclick=()=>action(button,async()=>{const peer=peers.find(p=>p.id===button.dataset.console);const result=await api('/console',{peer_ip:peer.ips[0]});location.assign(result.url);}));
 document.querySelectorAll('[data-forward]').forEach(button=>button.onclick=()=>openForward(button.dataset.forward,false));
 document.querySelectorAll('[data-connect]').forEach(button=>button.onclick=()=>action(button,async()=>{const peer=peers.find(p=>p.id===button.dataset.connect);await connect(peer,true,21118,0);}));
}
function openForward(id,desktop) {if(busy)return;selected=peers.find(peer=>peer.id===id);connecting=desktop;$('#forwardTitle').textContent=selected.hostname;$('#formError').textContent='';$('#remotePort').value='21118';$('#localPort').value='0';$('#forwardDialog').showModal();}
async function connect(peer,desktop,port,local) {
 const result=await api(desktop?'/connect':'/forwards',{peer_ip:peer.ips[0],remote_port:port,local_port:local});
 notice(result.launch_error || '连接入口 '+result.address);
 try {await refresh();} catch(error) {notice('连接已创建，列表刷新未完成。'+error.message,true);}
}
$('#search').oninput=renderPeers;
$('#refresh').onclick=event=>action(event.currentTarget,refresh);
$('#closeDialog').onclick=()=>{if(!busy)$('#forwardDialog').close();};
$('#forwardDialog').addEventListener('cancel',event=>{if(busy)event.preventDefault();});
$('#forwardForm').onsubmit=event=>{event.preventDefault();action($('#submitForward'),async()=>{try {await connect(selected,connecting,Number($('#remotePort').value),Number($('#localPort').value));$('#forwardDialog').close();} catch(error){$('#formError').textContent=error.message;}});};
$('#tokenForm').onsubmit=event=>{event.preventDefault();token=$('#tokenInput').value.trim();localStorage.setItem('orn-api-token',token);refresh().then(()=>notice('')).catch(error=>notice(error.message,true));};
$('#reconnect').onclick=event=>action(event.currentTarget,async()=>{await api('/control',{action:'reconnect'});await refresh();});
$('#disconnect').onclick=event=>{if(confirm('断开此设备的 ORN 网络？'))action(event.currentTarget,async()=>{await api('/control',{action:'disconnect'});await refresh();});};
$('#leave').onclick=event=>{if(confirm(sharedWithORH?'退出网络并解绑此设备的 Cloud 账号？ORH 统一登录也将失效，重新加入需要绑定。':'退出网络并解绑此设备？重新加入需要绑定。'))action(event.currentTarget,async()=>{await api('/leave',{confirm:true});await refresh();});};
$('#netcheck').onclick=event=>action(event.currentTarget,async()=>{$('#diagnostic').textContent=JSON.stringify(await api('/netcheck',{}),null,2);});
$('#bindForm').onsubmit=event=>{event.preventDefault();action(event.submitter,async()=>{await api('/cloud/bind',{cloud_url:$('#cloudURL').value.trim()});await refresh();});};
async function openIntent() {
 const mode=fragment.has('console')?'console':fragment.has('connect')?'connect':null;
 if(!mode) return;
 const directory=await api('/directory');
 const device=directory.find(row=>row.instance_id===fragment.get(mode));
 if(!device) throw Error('该设备不属于此 ORN 绑定的账号。请在 Cloud 和 ORN 使用相同账号。');
 const ip=device.mesh?.ips?.find(value=>!value.includes(':'));
 if(!ip) throw Error('目标设备尚未加入 ORN。');
 const result=await api('/'+mode,{peer_ip:ip,...(mode==='console'?{device_id:device.instance_id}:{remote_port:21118})});
 history.replaceState(null,'',location.pathname);
 if(mode==='console') location.assign(result.url);
 else notice(result.launch_error || '已启动远程桌面 '+result.address);
}
refresh().then(openIntent).catch(error=>notice(error.message,true));
setInterval(()=>{if(!document.hidden&&!busy&&!$('#forwardDialog').open)refresh().catch(error=>notice(error.message,true));},5000);
