import {setTheme, probe} from './portal.js';
import {bestURL} from './hosts.mjs';

const $ = selector => document.querySelector(selector);
const escapeHTML = value => String(value ?? '').replace(/[&<>"']/g, char => ({'&':'&amp;', '<':'&lt;', '>':'&gt;', '"':'&quot;', "'":'&#39;'}[char]));
let base = 'https://cloud.openremotehub.top';
let token = localStorage.getItem('orh-cloud-token') || '';
let user;
let devices = [];
let checking = false;
let mutating = false;
let refreshRequest;
let intent;
const results = new Map();
const icon = name => `<svg aria-hidden="true"><use href="./icons.svg#${name}"></use></svg>`;
const hostModel = device => ({urls:device.addresses,preferred:device.preferred});

async function api(path, body, method = body === undefined ? 'GET' : 'POST') {
  const headers = {'Content-Type':'application/json'};
  if (token && !['/api/login','/api/register'].includes(path)) headers.Authorization = 'Bearer ' + token;
  const response = await fetch(base+path, {method,headers,body:body === undefined ? undefined : JSON.stringify(body),credentials:'omit',signal:AbortSignal.timeout(15000)});
  let data;
  try { data = await response.json(); } catch { throw Error('Cloud 返回了无效响应，请检查服务地址。'); }
  if (response.status === 401 && !['/api/login','/api/register'].includes(path)) {
    token = ''; localStorage.removeItem('orh-cloud-token');
    loginPage();
  }
  if (!response.ok) throw Error(typeof data.detail === 'string' ? data.detail : '请求未完成，请核对输入。');
  return data;
}

function message(text, error = false) {
  const area = $('#cloudNotice');
  if (!area) return;
  area.hidden = !text; area.textContent = text; area.classList.toggle('error', error);
}

async function action(button, work) {
  if (mutating) return;
  mutating = true; button.disabled = true;
  try { await work(); }
  catch (error) { message(error.message, true); }
  finally { mutating = false; if (button.isConnected) button.disabled = false; }
}

function loginPage(register = false) {
  user = null;
  refreshRequest = null;
  document.querySelector('main').innerHTML = `<section class="cloud-login"><h1>OpenRemoteHub Cloud</h1><p class="muted">${register ? '创建账号，连接你的设备。' : '登录后访问你的设备。'}</p><form id="cloudLoginForm"><label for="cloudUsername">账号</label><input id="cloudUsername" autocomplete="username" required minlength="3" maxlength="80" pattern="[A-Za-z0-9][A-Za-z0-9_.@+\\-]*" placeholder="用户名或邮箱"><label for="cloudPassword">密码</label><input id="cloudPassword" type="password" autocomplete="${register ? 'new-password' : 'current-password'}" required maxlength="1024">${register ? '<label for="cloudInvitation">邀请码</label><input id="cloudInvitation" required maxlength="128" autocomplete="off">' : ''}<p id="cloudNotice" class="notice" role="alert" hidden></p><button class="primary" id="cloudLoginSubmit">${register ? '注册并登录' : '登录'}</button></form><button class="text-button" id="cloudSwitch">${register ? '已有账号，去登录' : '注册账号'}</button><details class="cloud-server"><summary>Cloud 服务地址</summary><input id="cloudServer" type="url" value="${escapeHTML(base)}" aria-label="Cloud 服务地址"></details></section>`;
  $('#cloudAccount')?.remove();
  $('#cloudSwitch').onclick = () => loginPage(!register);
  $('#cloudLoginForm').onsubmit = async event => {
    event.preventDefault();
    const submit = $('#cloudLoginSubmit');
    submit.disabled = true;
    try {
      const url = new URL($('#cloudServer').value.trim());
      if (!['https:','http:'].includes(url.protocol) || url.username || url.password) throw Error('请输入 Cloud 服务地址。');
      if (base !== url.origin) {token = ''; localStorage.removeItem('orh-cloud-token');}
      base = url.origin;
      localStorage.setItem('orh-cloud-url',base);
      const result = await api(register ? '/api/register' : '/api/login', {username:$('#cloudUsername').value.trim(),password:$('#cloudPassword').value,...(register ? {invitation:$('#cloudInvitation').value.trim()} : {})});
      token = result.token; user = result.user;
      localStorage.setItem('orh-cloud-token',token);
      await dashboard();
    } catch (error) { message(error.message,true); }
    finally { if (submit.isConnected) submit.disabled = false; }
  };
}

async function dashboard() {
  document.querySelector('main').innerHTML = `<div class="heading"><h1>我的设备</h1><button class="primary" id="bindDevice">${icon('plus')}绑定设备</button></div><div class="toolbar"><input id="cloudSearch" type="search" placeholder="搜索设备或地址" aria-label="搜索设备或地址"><div class="actions"><button id="refreshDevices">${icon('refresh-cw')}刷新设备</button><button id="checkDevices">检测连接</button></div></div><p id="cloudNotice" class="notice" role="status" hidden></p><div class="list-meta"><span id="cloudCount"></span><span id="cloudUpdated"></span></div><div id="cloudDevices" class="host-grid"></div>`;
  $('#cloudAccount')?.remove();
  const account = document.createElement('div');
  account.id = 'cloudAccount'; account.className = 'actions';
  account.innerHTML = `<span class="muted">${escapeHTML(user.username)}</span><button id="cloudLogout">退出登录</button>`;
  document.querySelector('header').insertBefore(account,$('#theme'));
  $('#cloudLogout').onclick = event => action(event.currentTarget,async () => {
    await api('/api/logout',{});
    token = ''; intent = null;
    localStorage.removeItem('orh-cloud-token'); sessionStorage.removeItem('orh-cloud-intent');
    loginPage();
  });
  $('#refreshDevices').onclick = event => action(event.currentTarget,loadDevices);
  $('#checkDevices').onclick = () => detect(devices);
  $('#cloudSearch').oninput = renderDevices;
  $('#bindDevice').onclick = () => bindingDialog();
  await loadDevices();
  if (intent?.bind) await bindingDialog(intent.bind);
  if (intent?.authorize) {
    const device = devices.find(row => row.instance_id === intent.authorize.device);
    if (!device) {
      message('该设备不属于当前账号，请使用绑定此设备的账号登录。',true);
      return;
    }
    await openDevice(device,intent.authorize.address,intent.authorize.state || '');
  }
}

async function loadDevices() {
  if (refreshRequest) return refreshRequest;
  const ownerToken = token;
  const pending = api('/api/devices').then(data => {
    if (!user || token !== ownerToken || !$('#cloudDevices')) return;
    devices = data;
    renderDevices();
    $('#cloudUpdated').textContent = '更新于 '+new Date().toLocaleTimeString();
  });
  refreshRequest = pending;
  try { await pending; } finally { if (refreshRequest === pending) refreshRequest = null; }
}

function renderDevices() {
  const query = $('#cloudSearch').value.toLowerCase();
  const rows = devices.filter(device => `${device.name} ${device.os} ${device.addresses.join(' ')}`.toLowerCase().includes(query));
  $('#cloudCount').textContent = `${devices.length} 台设备`;
  $('#cloudDevices').innerHTML = rows.map(device => {
    const reachable = device.addresses.filter(url => results.get(url)?.identity?.instance_id === device.instance_id);
    const checked = device.addresses.some(url => results.has(url));
    const mesh = device.mesh;
    const hasConsole = mesh?.services?.includes(8765);
    const hasDesktop = mesh?.services?.includes(21118);
    const connection = !device.addresses.length ? '通过本机 ORN 连接' : reachable.length ? `${reachable.length} 个地址可连接` : checked ? '浏览器未确认地址可达，可直接打开控制台' : '地址待检测';
    return `<article class="host-card"><div class="card-heading"><h2>${escapeHTML(device.name)}</h2><span class="state ${device.online ? 'online' : ''}">${device.online ? '在线' : '离线'}</span></div><small>${escapeHTML(device.os)}</small><p class="heartbeat">${device.last_seen ? '最近心跳 '+new Date(device.last_seen*1000).toLocaleString() : '等待 Agent 首次心跳'}</p><ul class="addresses">${(mesh?.ips || []).filter(ip => !ip.includes(':')).map(ip=>`<li class="address"><span class="state ${device.online ? 'online' : ''}"></span><span class="address-text">${escapeHTML(ip)} <span class="preferred">ORN</span></span></li>`).join('')}${device.addresses.map(url => `<li class="address"><span class="state ${reachable.includes(url) ? 'online' : ''}" title="${reachable.includes(url) ? '浏览器确认可连接' : '尚未确认连通'}"></span><button class="address-text address-open" data-address-device="${device.instance_id}" data-address="${escapeHTML(url)}" title="通过此地址打开控制台">${escapeHTML(url)}${url === device.preferred ? '<span class="preferred">首选</span>' : ''}</button></li>`).join('')}</ul><p class="host-feedback">${escapeHTML(connection)}${mesh?.paths?.length ? ' · '+mesh.paths.map(path=>path==='direct'?'直连':'中继').join(' / ') : ''}</p><div class="card-actions"><button class="primary" data-open-device="${device.instance_id}" ${device.addresses.length ? '' : 'disabled'}>${icon('external-link')}打开控制台</button>${hasConsole ? `<button data-orn-console="${device.instance_id}">${icon('external-link')}ORN 控制台</button>` : ''}${hasDesktop ? `<button data-orn-connect="${device.instance_id}">远程桌面</button>` : ''}${device.addresses.length ? `<button data-detect-device="${device.instance_id}">检测</button>` : ''}<button data-edit-device="${device.instance_id}">编辑</button><button class="remove" data-unbind-device="${device.instance_id}">解绑</button></div></article>`;
  }).join('') || `<div class="empty"><h2>${devices.length ? '没有匹配的设备' : '绑定你的第一台设备'}</h2><p>在 Agent 运行绑定命令后，输入一次性绑定码。</p><code>.venv/bin/python scripts/cloud_agent.py bind</code></div>`;
  document.querySelectorAll('[data-orn-console]').forEach(button => button.onclick = () => location.assign('http://127.0.0.1:4789/#console='+encodeURIComponent(button.dataset.ornConsole)));
  document.querySelectorAll('[data-orn-connect]').forEach(button => button.onclick = () => location.assign('http://127.0.0.1:4789/#connect='+encodeURIComponent(button.dataset.ornConnect)));
  document.querySelectorAll('[data-address-device]').forEach(button => button.onclick = () => action(button,() => openDevice(devices.find(row => row.instance_id === button.dataset.addressDevice),button.dataset.address)));
  document.querySelectorAll('[data-open-device]').forEach(button => button.onclick = () => action(button,() => openDevice(devices.find(row => row.instance_id === button.dataset.openDevice))));
  document.querySelectorAll('[data-detect-device]').forEach(button => button.onclick = () => detect([devices.find(row => row.instance_id === button.dataset.detectDevice)]));
  document.querySelectorAll('[data-edit-device]').forEach(button => button.onclick = () => editDevice(devices.find(row => row.instance_id === button.dataset.editDevice)));
  document.querySelectorAll('[data-unbind-device]').forEach(button => button.onclick = () => unbindDevice(devices.find(row => row.instance_id === button.dataset.unbindDevice),button));
}

async function openDevice(device, address, state = '') {
  if (!device.addresses.length) throw Error('设备尚无访问地址，请编辑地址或调整 Agent 监听设置。');
  // Only identities matching this device can influence automatic address choice.
  const matching = new Map(device.addresses.filter(url => results.get(url)?.identity?.instance_id === device.instance_id).map(url => [url,results.get(url)]));
  const selected = address || bestURL(hostModel(device),matching);
  const result = await api('/api/devices/'+device.instance_id+'/ticket',{address:selected,state});
  sessionStorage.removeItem('orh-cloud-intent');
  location.assign(result.url);
}

async function detect(selected) {
  if (checking) return;
  checking = true;
  $('#checkDevices').disabled = true;
  message('浏览器正在检测地址。如提示本地网络访问，请允许。设备在线状态由 Agent 心跳决定。');
  const controller = new AbortController();
  const queue = [...new Set(selected.flatMap(device => device.addresses))];
  let responded = false;
  async function worker() {
    while (queue.length && user) {
      const url = queue.shift();
      const result = await probe(url,controller.signal,responded ? 4000 : 120000);
      if (result.identity) responded = true;
      results.set(url,result);
      if ($('#cloudDevices')) renderDevices();
    }
  }
  try {
    await Promise.all(Array.from({length:Math.min(queue.length,6)},worker));
    message('地址检测已完成。未确认可达的地址仍可通过顶层页面直接打开。');
  } finally {
    checking = false;
    if ($('#checkDevices')) $('#checkDevices').disabled = false;
  }
}

function dialog(title, body) {
  $('#cloudDialog')?.remove();
  const element = document.createElement('dialog');
  element.id = 'cloudDialog';
  element.innerHTML = `<div class="dialog-heading"><h2>${escapeHTML(title)}</h2><button class="icon-button" id="closeCloudDialog" aria-label="关闭">${icon('x')}</button></div>${body}<p id="cloudDialogError" class="cloud-error" role="alert" hidden></p>`;
  document.body.append(element);
  $('#closeCloudDialog').onclick = () => {if (!mutating) element.close();};
  element.addEventListener('cancel',event => {if (mutating) event.preventDefault();});
  element.showModal();
  return element;
}

async function bindingDialog(code = '') {
  const element = dialog('绑定设备',`<form id="bindingForm"><label for="bindingCode">一次性绑定码</label><input id="bindingCode" autocomplete="off" required value="${escapeHTML(code)}" placeholder="XXXX-XXXX"><div id="bindingPreview"></div><div class="dialog-actions"><button class="primary" id="bindingSubmit">查看设备</button></div></form>`);
  let previewed = '';
  async function preview() {
    const entered = $('#bindingCode').value.trim();
    const device = await api('/api/bindings/'+encodeURIComponent(entered));
    previewed = entered;
    $('#bindingPreview').innerHTML = `<h3>${escapeHTML(device.name)}</h3><p class="muted">${escapeHTML(device.os)}</p><p class="mono">${device.addresses.map(escapeHTML).join('<br>')}</p>`;
    $('#bindingSubmit').textContent = '绑定到当前账号';
  }
  $('#bindingCode').oninput = () => {previewed = ''; $('#bindingSubmit').textContent = '查看设备';};
  $('#bindingForm').onsubmit = event => {
    event.preventDefault();
    const button = $('#bindingSubmit');
    action(button,async () => {
      try {
        if (previewed !== $('#bindingCode').value.trim()) {await preview(); return;}
        await api('/api/bindings/approve',{code:previewed});
        intent = null; sessionStorage.removeItem('orh-cloud-intent');
        element.close();
        await loadDevices();
        message('设备已绑定。');
      } catch (error) {
        $('#cloudDialogError').textContent = error.message; $('#cloudDialogError').hidden = false;
      }
    });
  };
  if (code) {
    try {await preview();} catch (error) {$('#cloudDialogError').textContent=error.message;$('#cloudDialogError').hidden=false;}
  }
}

function editDevice(device) {
  const element = dialog('编辑设备',`<form id="deviceEditForm"><label for="deviceName">名称</label><input id="deviceName" required maxlength="160" value="${escapeHTML(device.name)}"><label for="deviceAddresses">访问地址</label><textarea id="deviceAddresses" rows="5" ${device.kind==='orn' ? '' : 'required'}>${escapeHTML(device.addresses.join('\n'))}</textarea><label for="devicePreferred">首选地址</label><select id="devicePreferred"><option value="">自动选择可达地址</option>${device.addresses.map(url => `<option value="${escapeHTML(url)}" ${url===device.preferred?'selected':''}>${escapeHTML(url)}</option>`).join('')}</select><div class="dialog-actions"><button class="primary" id="deviceSave">保存</button></div></form>`);
  $('#deviceAddresses').oninput = () => {
    const selected = $('#devicePreferred').value;
    const urls = $('#deviceAddresses').value.split('\n').map(value=>value.trim()).filter(Boolean);
    $('#devicePreferred').innerHTML = '<option value="">自动选择可达地址</option>' + urls.map(url=>`<option value="${escapeHTML(url)}" ${url===selected?'selected':''}>${escapeHTML(url)}</option>`).join('');
  };
  $('#deviceEditForm').onsubmit = event => {
    event.preventDefault();
    action($('#deviceSave'),async () => {
      try {
        await api('/api/devices/'+device.instance_id,{name:$('#deviceName').value.trim(),addresses:$('#deviceAddresses').value.split('\n').map(value => value.trim()).filter(Boolean),preferred:$('#devicePreferred').value || null},'PATCH');
        element.close(); await loadDevices();
      } catch (error) {$('#cloudDialogError').textContent=error.message;$('#cloudDialogError').hidden=false;}
    });
  };
}

function unbindDevice(device, button) {
  const element = dialog('解绑设备',`<p>将 ${escapeHTML(device.name)} 从当前账号解绑，Agent 会在下次心跳时撤销 Cloud 登录。</p><div class="dialog-actions"><button id="confirmUnbind" class="remove">解绑设备</button></div>`);
  $('#confirmUnbind').onclick = event => action(event.currentTarget,async () => {
    await api('/api/devices/'+device.instance_id,undefined,'DELETE');
    element.close(); await loadDevices();
  });
}

async function start() {
  document.title = 'OpenRemoteHub Cloud · 我的设备';
  try {
    const config = await fetch('./cloud-config.json',{cache:'no-store'}).then(response=>response.json());
    base = config.url || base;
  } catch { /* A user can select another endpoint in the login form. */ }
  base = localStorage.getItem('orh-cloud-url') || base;
  setTheme((localStorage.getItem('openremotehub.portal.theme') || (matchMedia('(prefers-color-scheme: dark)').matches ? 'dark':'light')) === 'dark');
  const hash = new URLSearchParams(location.hash.slice(1));
  if (hash.has('bind')) intent = {bind:hash.get('bind')};
  if (hash.has('authorize')) {
    try {intent = {authorize:JSON.parse(hash.get('authorize'))};} catch {intent = null;}
  }
  if (intent) {
    sessionStorage.setItem('orh-cloud-intent',JSON.stringify(intent));
    history.replaceState(null,'',location.pathname+location.search);
  } else {
    try {intent = JSON.parse(sessionStorage.getItem('orh-cloud-intent') || 'null');} catch {intent=null;}
  }
  document.querySelector('footer').innerHTML = '<span>OpenRemoteHub Cloud</span><a href="?local=1">独立主机列表</a>';
  if (token) {
    try {user = await api('/api/me'); await dashboard(); return;} catch (error) {loginPage(); message(error.message,true); return;}
  }
  loginPage();
}
setInterval(() => {
  if (user && !document.hidden && !mutating && !$('#cloudDialog')?.open) loadDevices().catch(error=>message(error.message,true));
},15000);
if (!new URLSearchParams(location.search).has('local')) {
  if (new URLSearchParams(location.hash.slice(1)).has('add')) location.replace('?local=1'+location.hash);
  else start();
}
