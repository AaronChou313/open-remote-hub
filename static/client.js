'use strict';
const select = selector => document.querySelector(selector);
const escapeHTML = value => String(value ?? '').replace(/[&<>"']/g, character => ({'&':'&amp;', '<':'&lt;', '>':'&gt;', '"':'&quot;', "'":'&#39;'}[character]));
const pathLabels = {local:'本机', direct:'P2P 直连', relay:'DERP 中继', idle:'链路尚未建立'};
let currentDeviceId = null;
let directory;
let account;
let connecting = false;
let refreshing = false;
let page='devices';
sessionStorage.removeItem('orh-current-device');
if (localStorage.getItem('orh-theme') === 'dark' || (!localStorage.getItem('orh-theme') && matchMedia('(prefers-color-scheme: dark)').matches)) document.body.classList.add('dark');


async function request(path, body) {
  const response = await fetch('/api' + path, {
    method: body === undefined ? 'GET' : 'POST',
    headers: body === undefined ? {} : {'Content-Type':'application/json', 'X-ORH-Request':'1'},
    body: body === undefined ? undefined : JSON.stringify(body),
    signal: AbortSignal.timeout(60000),
  });
  const value = await response.json();
  if (!response.ok) {
    if (response.status === 401) await showLogin();
    const error = Error(typeof value.detail === 'string' ? value.detail : value.detail?.message || '请求失败，请重试');
    error.module = value.detail?.module;
    throw error;
  }
  return value;
}

async function showLogin() {
  if(typeof RemoteHubAgentSettings!=='undefined')RemoteHubAgentSettings.reset();
  if(typeof RemoteHubMesh!=='undefined')RemoteHubMesh.reset();
  select('#clientAgentSettings').innerHTML='';select('#clientMesh').innerHTML='';
  window.RemoteHubSoftware?.reset();
  directory=null;account=null;
  select('#clientShell').hidden = true;
  select('#clientLogin').hidden = false;
  const response = await fetch('/api/auth/status');
  const status = await response.json();
  select('#clientCloud').value = status.cloud?.cloud_url || 'https://cloud.openremotehub.top';
  select('#clientCloud').readOnly = Boolean(status.cloud?.bound);
  select('#clientRecovery').hidden = !(status.recovery_enabled || (!status.cloud?.bound && status.local_password_set));
}

function renderDirectory() {
  directory ||= {devices:[],cloud:{bound:Boolean(account.cloud?.bound),error:''},mesh:{}};
  select('#clientNotice').textContent = directory.cloud.error || (!directory.cloud.bound ? '本机独立模式。登录 ORH 账号后可查看同账号设备。' : directory.mesh.error || '');
  select('#clientDevices').innerHTML = directory.devices.map(device => `
    <article class="client-device">
      <div class="client-device-info"><h2>${escapeHTML(device.name)}${device.local ? ' <span class="badge">本机</span>' : ''}</h2>
        <p>${escapeHTML(device.os)} · ${!directory.cloud.bound ? '未绑定 Cloud' : directory.cloud.error ? 'Cloud 心跳待确认' : device.heartbeat_online ? 'Cloud 心跳在线' : 'Cloud 心跳离线'} · ${pathLabels[device.path] || pathLabels.idle}</p>
        <p>${escapeHTML(device.mesh_ips.join(' · '))}${device.agent_published ? '' : ' · 未发布 Agent 管理能力'}</p>
      </div>
      <div class="toolbar"><button class="primary" data-connect="${escapeHTML(device.device_id)}" ${device.agent_published ? '' : 'disabled'}>打开控制台</button>
        ${device.desktop_published ? `<button data-desktop="${escapeHTML(device.device_id)}">远程桌面</button>` : ''}</div>
    </article>`).join('');
  const details = values => values.map(([name, value]) => `<div><dt>${escapeHTML(name)}</dt><dd>${escapeHTML(value)}</dd></div>`).join('');
  select('#clientAccount').innerHTML = details([
    ['账号', account.cloud?.username || '本机独立模式'],
    ['Cloud', account.cloud?.cloud_url || '尚未绑定'],
    ['本机', account.host.hostname],
    ['后台', '窗口关闭后继续运行'],
  ]);
  select('#clientCloudAdmin').href = (account.cloud?.cloud_url || 'https://cloud.openremotehub.top') + '/';
  const localWorkspace = new URL('/', location.href);
  localWorkspace.search = new URLSearchParams({client:location.origin + '/client', device_id:account.device_id, device_name:account.host.hostname});
  localWorkspace.hash = 'modules';
  select('#clientModules').href = localWorkspace.href;
}

async function refreshDevices() {
  if (refreshing || connecting) return;
  refreshing = true;
  select('#clientRefresh').disabled = true;
  try {
    account = await request('/me');
    if(page==='devices')directory = await request('/client/devices');
    select('#clientLogin').hidden = true;
    select('#clientShell').hidden = false;
    select('#clientError').hidden = true;
    renderDirectory();
    if(page==='mesh')await RemoteHubMesh.render(()=>page==='mesh','#clientMesh',request);
    if(page==='about')await RemoteHubSoftware.render(()=>page==='about','#clientAbout',request);
    if(page==='settings')await RemoteHubAgentSettings.render(()=>page==='settings','#clientAgentSettings',request);
  } catch (error) {
    const loginVisible = !select('#clientLogin').hidden;
    if (!loginVisible) select('#clientShell').hidden = false;
    const target = select(loginVisible ? '#clientLoginError' : '#clientError');
    target.textContent = error.name === 'TypeError' ? '本机 Agent 无法访问，请检查后台服务后刷新' : error.message;
    target.hidden = false;
  } finally {
    refreshing = false;
    select('#clientRefresh').disabled = false;
  }
}

select('#clientLoginForm').onsubmit = async event => {
  event.preventDefault();
  const button = select('#clientSignIn');
  button.disabled = true;
  select('#clientLoginError').textContent = '';
  try {
    await request('/auth/client/login', {cloud_url:select('#clientCloud').value.trim(), username:select('#clientUser').value.trim(), password:select('#clientPassword').value});
    select('#clientPassword').value = '';
    await refreshDevices();
  } catch (error) {
    select('#clientLoginError').textContent = error.message;
  } finally {
    button.disabled = false;
  }
};

select('#clientDevices').onclick = async event => {
  const button = event.target.closest('button[data-connect], button[data-desktop]');
  if (!button || connecting) return;
  connecting = true;
  button.disabled = true;
  const label = button.textContent;
  button.textContent = '正在连接…';
  select('#clientError').hidden = true;
  try {
    const deviceId = button.dataset.connect || button.dataset.desktop;
    const result = await request(button.dataset.connect ? '/client/connect' : '/client/desktop', {device_id:deviceId});
    if (button.dataset.connect) {
      currentDeviceId = result.device_id;
      sessionStorage.setItem('orh-current-device', currentDeviceId);
      const targetURL=new URL(result.url,location.href);
      const theme=localStorage.getItem('orh-theme');
      if(theme)targetURL.searchParams.set('client_theme',theme);
      location.assign(targetURL.href);
    } else select('#clientNotice').textContent = '已启动本机 RustDesk';
  } catch (error) {
    if (error.module && account) {
      const workspace = await request('/client/connect', {device_id:account.device_id});
      const address = new URL(workspace.url, location.origin);
      address.hash = 'modules';
      location.assign(address.href);
      return;
    }
    select('#clientError').textContent = error.message;
    select('#clientError').hidden = false;
  } finally {
    connecting = false;
    button.disabled = false;
    button.textContent = label;
  }
};

async function showPage(next, load = true) {
  if(page==='settings'&&!await RemoteHubAgentSettings.canLeave())return;
  if(page==='mesh'&&!await RemoteHubMesh.canLeave())return;
  if(!['devices','mesh','settings','about'].includes(next))next='devices';
  page=next;
  for(const name of ['devices','mesh','settings','about'])select('#client'+name[0].toUpperCase()+name.slice(1)).hidden=name!==page;
  document.querySelectorAll('button[data-page]').forEach(button=>button.setAttribute('aria-current',button.dataset.page===page?'page':'false'));
  select('#clientTitle').textContent={devices:'我的设备',mesh:'组网状态',settings:'设置',about:'关于 ORH'}[page];
  if(load)await refreshDevices();
}
document.querySelectorAll('button[data-page]').forEach(button=>button.onclick=()=>showPage(button.dataset.page));
window.addEventListener?.('hashchange',()=>showPage(location.hash.slice(1)));
select('#clientAppearance').value=localStorage.getItem('orh-theme')||'system';
select('#clientAppearance').onchange=()=>{
 const value=select('#clientAppearance').value;
 if(value==='system')localStorage.removeItem('orh-theme');else localStorage.setItem('orh-theme',value);
 document.body.classList.toggle('dark',value==='dark'||value==='system'&&matchMedia('(prefers-color-scheme: dark)').matches);
};
select('#clientRecoveryPassword').onkeydown=event=>{if(event.key==='Enter'){event.preventDefault();select('#clientRecoveryLogin').click()}};
select('#clientRecoveryLogin').onclick=async()=>{
 try{await request('/login',{password:select('#clientRecoveryPassword').value});select('#clientRecoveryPassword').value='';await refreshDevices()}catch(error){select('#clientLoginError').textContent=error.message}
};
select('#clientRefresh').onclick = refreshDevices;
select('#clientLogout').onclick = async () => {
  try { await request('/auth/client/logout', {}); await showLogin(); }
  catch (error) { select('#clientError').textContent = error.message; select('#clientError').hidden = false; }
};
select('#clientRegister').onclick = () => { select('#clientRegister').href = select('#clientCloud').value.trim().replace(/\/+$/, '') + '/#register'; };
setInterval(() => { if (!document.hidden && !select('#clientShell').hidden) refreshDevices(); }, 15000);
if(['#about','#settings','#mesh'].includes(location.hash))showPage(location.hash.slice(1),false);
refreshDevices();
