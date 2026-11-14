import {STORAGE_KEY, normalizeHost, isIdentity, addressSpace, mergeIdentities, bestURL} from './hosts.mjs';

const $ = selector => document.querySelector(selector);
const results = new Map();
let hosts = [];
let editing = null;
let request = null;
let autoCheck = false;
const escapeHTML = value => String(value).replace(/[&<>"']/g, char => ({'&':'&amp;', '<':'&lt;', '>':'&gt;', '"':'&quot;', "'":'&#39;'}[char]));
const icon = name => `<svg aria-hidden="true"><use href="./icons.svg#${name}"></use></svg>`;

function notice(message, error = false) {
  $('#notice').textContent = message;
  $('#notice').hidden = !message;
  $('#notice').classList.toggle('error', error);
}

function save() {
  try { localStorage.setItem(STORAGE_KEY, JSON.stringify({version:1, hosts})); }
  catch { notice('浏览器未能保存主机列表，请导出备份，或允许此站点使用本地存储。', true); }
}

function addHosts(values) {
  if (!Array.isArray(values)) throw Error('主机列表格式错误。');
  const incoming = values.map(normalizeHost);
  for (const host of incoming) {
    const existing = hosts.find(row => host.instanceId && row.instanceId === host.instanceId || row.urls.some(url => host.urls.includes(url)));
    if (existing) {
      existing.urls = [...new Set([...existing.urls, ...host.urls])];
      if (!existing.name) existing.name = host.name;
      if (!existing.instanceId) existing.instanceId = host.instanceId;
    } else hosts.push(host);
  }
  save();
  render();
}

function render() {
  const query = $('#search').value.trim().toLowerCase();
  const visible = hosts.filter(host => `${host.name} ${host.urls.join(' ')}`.toLowerCase().includes(query))
    .sort((a, b) => (a.name || a.urls[0]).localeCompare(b.name || b.urls[0], 'zh-CN', {numeric:true}));
  $('#empty').hidden = hosts.length > 0;
  $('#exportHosts').disabled = !hosts.length;
  $('#count').textContent = hosts.length ? `${hosts.length} 台主机` : '';
  $('#hosts').innerHTML = visible.map(host => {
    const target = bestURL(host, results);
    const available = host.urls.filter(url => results.get(url)?.identity);
    const tested = host.urls.some(url => results.has(url));
    const status = available.length ? '可连接' : request ? '检测中' : tested ? '未能检测' : '待检测';
    const addresses = host.urls.map(url => `<li class="address"><span class="state ${results.get(url)?.identity ? 'online' : ''}" title="${results.get(url)?.identity ? '可连接' : '未确认连通'}"></span><a href="${escapeHTML(url)}" target="_blank" rel="noopener noreferrer">${escapeHTML(url)}${url === host.preferred ? '<span class="preferred">首选</span>' : ''}</a></li>`).join('');
    const feedback = tested && !available.length ? '<p class="host-feedback">可直接打开地址，或检查组网连接、浏览器本地网络权限及后端版本。</p>' : '';
    return `<article class="host-card"><div class="card-heading"><h2>${escapeHTML(host.name || new URL(target).hostname)}</h2><span class="state ${available.length ? 'online' : ''}">${status}</span></div><small>${available.length ? `${available.length} 个地址可连接` : `${host.urls.length} 个访问地址`}</small><ul class="addresses">${addresses}</ul>${feedback}<div class="card-actions"><a class="button primary" href="${escapeHTML(target)}" target="_blank" rel="noopener noreferrer">${icon('external-link')}${available.length ? '进入控制台' : '直接打开'}</a><button data-check="${host.id}" ${request ? 'disabled' : ''}>检测</button><button data-edit="${host.id}">编辑</button><button data-remove="${host.id}" class="remove" aria-label="移除 ${escapeHTML(host.name || target)}">移除</button></div></article>`;
  }).join('') || (hosts.length ? '<p class="no-results">没有匹配的主机</p>' : '');
  document.querySelectorAll('[data-check]').forEach(button => button.onclick = () => check(hosts.find(host => host.id === button.dataset.check).urls));
  document.querySelectorAll('[data-edit]').forEach(button => button.onclick = () => edit(hosts.find(host => host.id === button.dataset.edit)));
  document.querySelectorAll('[data-remove]').forEach(button => button.onclick = () => {
    hosts = hosts.filter(host => host.id !== button.dataset.remove);
    save(); render();
  });
}

async function probe(url, signal) {
  const controller = new AbortController();
  const abort = () => controller.abort();
  signal.addEventListener('abort', abort, {once:true});
  const timeout = setTimeout(abort, 4000);
  const began = performance.now();
  try {
    const options = {signal:controller.signal, mode:'cors', credentials:'omit', cache:'no-store', redirect:'error'};
    const space = addressSpace(url);
    if (space) options.targetAddressSpace = space;
    const response = await fetch(url + '/.well-known/openremotehub', options);
    if (!response.ok) throw Error(`HTTP ${response.status}`);
    const value = await response.json();
    if (!isIdentity(value)) throw Error('目标未返回 RemoteHub 服务标识');
    return {identity:value, latency:performance.now() - began};
  } catch (error) {
    return {error:error.name === 'AbortError' ? '连接超时或检测取消' : error.message};
  } finally {
    clearTimeout(timeout);
    signal.removeEventListener('abort', abort);
  }
}

async function check(urls = hosts.flatMap(host => host.urls)) {
  if (request) { request.abort(); return; }
  if (!urls.length) { edit(); return; }
  const controller = new AbortController();
  let complete;
  request = {abort:() => controller.abort(), done:new Promise(resolve => { complete = resolve; })};
  autoCheck = true;
  $('#checkAll').innerHTML = icon('square') + '<span>取消检测</span>';
  notice('如浏览器询问本地网络访问权限，请允许，以检测主机是否可连接。');
  render();
  const queue = [...new Set(urls)];
  async function worker() {
    while (queue.length && !controller.signal.aborted) {
      const url = queue.shift();
      const result = await probe(url, controller.signal);
      if (!controller.signal.aborted) results.set(url, result);
    }
  }
  try {
    await Promise.all(Array.from({length:Math.min(queue.length, 6)}, worker));
    hosts = mergeIdentities(hosts, results);
    save();
    $('#checked').textContent = '检测于 ' + new Date().toLocaleTimeString();
    const online = hosts.filter(host => host.urls.some(url => results.get(url)?.identity)).length;
    if (online) {
      try { localStorage.setItem('openremotehub.portal.detect', '1'); } catch {}
    }
    notice(controller.signal.aborted ? '检测已取消。' : online ? '' : '暂未检测到可连接的主机。可直接打开已保存地址，或在浏览器站点设置中允许本地网络访问。');
  } finally {
    request = null;
    complete();
    $('#checkAll').innerHTML = icon('refresh-cw') + '<span>检测连接</span>';
    render();
  }
}

function edit(host = null) {
  editing = host?.id || null;
  $('#dialogTitle').textContent = host ? '编辑主机' : '添加主机';
  $('#hostName').value = host?.name || '';
  $('#hostUrls').value = host?.urls.join('\n') || '';
  $('#formError').hidden = true;
  $('#hostDialog').showModal();
  (host ? $('#hostName') : $('#hostUrls')).focus();
}

$('#hostForm').onsubmit = async event => {
  event.preventDefault();
  try {
    const host = normalizeHost({name:$('#hostName').value, urls:$('#hostUrls').value.split(/\n/).filter(value => value.trim())});
    if (editing) {
      const previous = hosts.find(row => row.id === editing);
      host.id = editing;
      host.instanceId = previous?.instanceId || null;
      hosts = hosts.map(row => row.id === editing ? host : row);
      save(); render();
    } else addHosts([host]);
    $('#hostDialog').close();
    if (request) {
      const previous = request;
      previous.abort();
      await previous.done;
    }
    check(host.urls);
  } catch (error) {
    $('#formError').textContent = error.message;
    $('#formError').hidden = false;
  }
};
$('#addHost').onclick = () => edit();
$('#emptyAdd').onclick = () => edit();
$('#closeDialog').onclick = $('#cancelDialog').onclick = () => $('#hostDialog').close();
$('#search').oninput = render;
$('#checkAll').onclick = () => check();
$('#importHosts').onclick = () => $('#importFile').click();
$('#importFile').onchange = async event => {
  const file = event.target.files[0];
  if (!file) return;
  try {
    if (file.size > 256 * 1024) throw Error('主机列表文件请保持在 256 KiB 以内。');
    const data = JSON.parse(await file.text());
    if (data.version !== 1) throw Error('不支持此版本的主机列表。');
    addHosts(data.hosts);
    notice('主机列表已导入，点击“检测连接”检查可用地址。');
  } catch (error) { notice(error.message, true); }
  event.target.value = '';
};
$('#exportHosts').onclick = () => {
  const url = URL.createObjectURL(new Blob([JSON.stringify({version:1, hosts}, null, 2)], {type:'application/json'}));
  const link = document.createElement('a');
  link.href = url; link.download = 'remotehub-hosts.json'; link.click();
  setTimeout(() => URL.revokeObjectURL(url), 1000);
};
function setTheme(dark) {
  document.documentElement.classList.toggle('dark', dark);
  $('#theme').innerHTML = icon(dark ? 'sun' : 'moon');
  $('#theme').setAttribute('aria-label', dark ? '切换为浅色模式' : '切换为暗色模式');
}
$('#theme').onclick = () => {
  const dark = !document.documentElement.classList.contains('dark');
  setTheme(dark);
  try { localStorage.setItem('openremotehub.portal.theme', dark ? 'dark' : 'light'); } catch {}
};

async function start() {
  try {
    setTheme((localStorage.getItem('openremotehub.portal.theme') || (matchMedia('(prefers-color-scheme: dark)').matches ? 'dark' : 'light')) === 'dark');
    const stored = localStorage.getItem(STORAGE_KEY);
    if (stored) {
      const data = JSON.parse(stored);
      if (data.version !== 1 || !Array.isArray(data.hosts)) throw Error('保存的主机列表格式不受支持，请重新导入。');
      hosts = data.hosts.map(normalizeHost);
    }
  } catch (error) { notice('无法读取主机列表。' + error.message, true); }
  try {
    const hash = new URLSearchParams(location.hash.slice(1));
    if (hash.has('add')) {
      addHosts([JSON.parse(hash.get('add'))]);
      history.replaceState(null, '', location.pathname + location.search);
      notice('主机已添加，点击“检测连接”检查可用地址。');
    }
  } catch (error) { notice('添加链接无效。' + error.message, true); }
  render();
  // Query both current and older Chrome permission names. A grant can arrive
  // after the initial request timed out while the user read the browser prompt.
  if (hosts.length && navigator.permissions) {
    let permission = null;
    for (const name of ['local-network', 'local-network-access']) {
      try { permission = await navigator.permissions.query({name}); break; }
      catch { /* Try the permission name supported by this browser. */ }
    }
    if (permission) {
      permission.addEventListener('change', async () => {
        if (permission.state === 'granted') {
          if (request) {
            const previous = request;
            previous.abort();
            await previous.done;
          }
          check();
        } else if (permission.state === 'denied') {
          autoCheck = false;
          request?.abort();
          notice('本地网络访问被浏览器阻止，请在站点设置中允许后重新检测。');
        }
      });
      if (permission.state === 'granted') check();
      else if (permission.state === 'denied') notice('本地网络访问被浏览器阻止，请在站点设置中允许后重新检测。');
    } else {
      try { if (localStorage.getItem('openremotehub.portal.detect') === '1') check(); } catch {}
    }
  }
}
setInterval(() => {
  if (autoCheck && hosts.length && !document.hidden && !request && !$('#hostDialog').open) check();
}, 30000);
start();
