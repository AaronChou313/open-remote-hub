'use strict';
window.RemoteHubDsh = (() => {
  async function render(check) {
    const d = await api('/dsh/status');
    if (!check()) return;
    const url = new URL(location.href);
    url.port = d.gateway_port; url.pathname = '/'; url.search = ''; url.hash = '';
    const labels = {disabled:'尚未启用',missing_dependency:'等待安装',running:'已连接',needs_auth:'需要恢复认证',stopped:'可以启动'};
    $('#content').innerHTML = `<section><div class="dsh-toolbar"><span class="badge">DSH ${esc(d.version || '未安装')}</span><span class="muted">${labels[d.state] || (d.running ? '已连接' : '可以启动')}</span>${d.running ? `<a class="button" href="${esc(url.href)}" target="_blank" rel="noopener">独立窗口 ${icon('external')}</a>` : d.installed && d.enabled ? `<button id="dshStart" class="primary">${d.state === 'needs_auth' ? '恢复认证并进入' : '启动并进入 DSH'}</button>` : ''}${d.managed ? '<button id="dshRestart">重启 DSH</button>' : ''}</div>${d.running ? `<iframe id="dshFrame" title="DeepSeek Harness 原生 Web" src="${esc(url.href)}" allow="clipboard-write; fullscreen"></iframe>` : `<article class="panel"><h2>${d.installed ? '连接本机 DSH' : '安装 DeepSeek Harness'}</h2><p>${d.state === 'needs_auth' ? '检测到正在运行的 DSH，将尝试接续它的本机认证。外部启动且无法认证的实例，请在原客户端退出后回到此页启动。' : d.installed ? '使用目标设备已有的 DSH 配置、插件和会话。首次进入后，在 DSH 原生界面完成模型账号和工作目录配置。' : '在目标设备安装 DeepSeek Harness 桌面版或 dsh 命令，再点击重新检测。ORH 会自动识别现有安装。自定义安装路径可在目标设备的 .env 中设置 ORH_DSH_BIN。'}</p><div class="toolbar">${!d.enabled ? '<button id="dshEnable" class="primary">启用 DSH 模块</button>' : ''}${!d.installed ? '<a class="button" href="https://www.npmjs.com/package/@deepseek-ai/dsh" target="_blank" rel="noopener">安装说明 ↗</a><button id="dshCheck">重新检测</button>' : ''}</div></article>`}</section>`;
    const action = (selector, key, work) => {
      const button = $(selector);
      if (button) button.onclick = async () => {
        try { await withBusy(button, key, '连接中…', work); if (check()) await render(check); }
        catch (error) { showError(error); }
      };
    };
    action('#dshStart', 'dsh:start', () => api(d.state === 'needs_auth' ? '/dsh/recover' : '/dsh/start', {}));
    action('#dshCheck', 'dsh:check', () => api('/modules/dsh/check', {}));
    action('#dshEnable', 'dsh:enable', () => api('/modules/dsh/enable', {}));
    action('#dshRestart', 'dsh:restart', async () => {
      if (await confirmAction('重启 DSH', '正在运行的模型任务会中断，确认单独重启 DSH？')) await api('/dsh/restart', {confirm:true});
    });
  }
  return {render};
})();
