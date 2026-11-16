'use strict';
// Each workspace retains the Agent's isolated gateway origin and module pages.
window.ORHClientWorkspace = (() => {
  const params = new URLSearchParams(location.search);
  const home = params.get('client');
  const android = params.get('android_client') === '1';
  if (!home && !android) return null;
  let clientHome;
  try {
    if (!android) {
      clientHome = new URL(home);
      if (!['http:', 'https:'].includes(clientHome.protocol) || clientHome.username || clientHome.password || clientHome.pathname !== '/client') return null;
    }
  } catch { return null; }
  document.body.classList.add('client-workspace');
  if (android) document.body.classList.add('android-client');
  const bar = document.createElement('div');
  bar.className = 'client-workspacebar';
  const back = document.createElement('a');
  back.href = android ? '#' : clientHome.href;
  back.className = 'button';
  back.textContent = '← 我的设备';
  const name = document.createElement('strong');
  name.textContent = params.get('device_name') || '设备工作区';
  const status = document.createElement('span');
  status.setAttribute('role', 'status');
  status.textContent = '正在连接 Agent…';
  bar.append(back, name, status);
  document.body.prepend(bar);
  let connected = false;
  const pathLabels = {direct:'P2P 直连', relay:'DERP 中继', idle:'链路尚未建立'};
  async function updateLink() {
    if (!connected || document.hidden) return;
    try {
      const result = await api('/client/link?peer_ip=' + encodeURIComponent(params.get('peer_ip')));
      if (!connected) return;
      if (!params.get('peer_ip')) { status.textContent = 'Agent 已连接 · 本机'; return; }
      status.textContent = 'Agent 已连接 · ' + (result.error || (result.state === 'Running' ? pathLabels[result.path] || pathLabels.idle : 'Mesh 尚未连接'));
    } catch (error) { if (connected) status.textContent = 'Agent API 不可达 · ' + error.message; }
  }
  window.addEventListener('orh:authenticated', event => {
    if (params.get('device_id') !== event.detail.device_id) {
      status.textContent = '目标设备身份不匹配，请返回设备列表重新连接';
      document.querySelector('#shell').hidden = true;
      return;
    }
    connected = true;
    window.ORHAndroid?.agentReady(true);
    name.textContent = (params.get('device_name') || event.detail.host.hostname) + ' · ' + event.detail.host.system;
    updateLink();
  });
  window.addEventListener('orh:login-required', () => { connected = false; window.ORHAndroid?.agentReady(false); status.textContent = 'Agent 登录已失效，请返回设备列表重新连接'; });
  setInterval(updateLink, 10000);
  function openTerminal(path) {
    if (window.ORHAndroid) { window.ORHAndroid.openTerminal(new URL(path, location.origin).href); return true; }
    if (!window.pywebview?.state) return false;
    window.pywebview.state.terminal_request = {url:new URL(path, location.origin).href, sequence:performance.now()};
    return true;
  }
  function bindNativeState() {
    window.pywebview?.state?.addEventListener('change', event => {
      if (event.detail.key === 'terminal_error') showError(Error(event.detail.value));
    });
  }
  window.addEventListener('pywebviewready', bindNativeState);
  document.addEventListener('click', event => {
    const anchor = event.target.closest('a[href]');
    if (!anchor) return;
    const target = new URL(anchor.href, location.href);
    if (target.origin === location.origin && target.pathname.startsWith('/terminal/open/') && (window.pywebview?.state || window.ORHAndroid)) {
      event.preventDefault();
      openTerminal(target.href);
    }
  });
  async function returnToDevices() {
    for (const module of [window.RemoteHubWorkspace, window.RemoteHubKnowledge, window.RemoteHubSSH, window.RemoteHubProxyManager, window.RemoteHubRemoteConnect, window.RemoteHubApplications, window.RemoteHubAgentSettings, window.RemoteHubMesh]) {
      if (module?.canLeave && !await module.canLeave()) return;
    }
    if (android) window.ORHAndroid?.returnToDevices();
    else location.assign(clientHome.href);
  }
  back.onclick = event => { event.preventDefault(); returnToDevices(); };
  const sidebarHome=document.querySelector('aside nav a[href="/client"]');
  if(sidebarHome){sidebarHome.href=back.href;sidebarHome.onclick=back.onclick;}
  return {openTerminal, returnToDevices};
})();
