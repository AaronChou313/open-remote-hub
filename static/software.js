'use strict';
window.RemoteHubSoftware = (() => {
  let timer;
  async function render(check, target, api) {
    clearTimeout(timer);
    const data = await api('/client/software');
    if (!check()) return;
    const root = document.querySelector(target);
    const esc = RemoteHubFormControls.escape;
    const labels = {idle:'检查是否有可用更新',checking:'正在检查更新…',current:'当前已是最新版本',available:'有新版本可用',downloading:'正在下载安装包…',ready:'更新已下载完成',installing:'安装程序正在启动，请按提示完成更新',error:'更新操作遇到问题'};
    const release = data.release;
    root.innerHTML = `<section class="about-product"><img src="/static/orh-logo.png" alt=""><div><h2>OpenRemoteHub</h2><p>私有组网与远程设备管理控制台</p><span class="version-label">版本 ${esc(data.version)} · ${esc(data.platform)} ${esc(data.architecture)}</span></div></section><section class="settings-section update-section"><div class="section-heading"><h2>软件更新</h2><span class="badge">${esc(labels[data.phase])}</span></div><dl class="settings-facts"><div><dt>当前版本</dt><dd>${esc(data.version)}</dd></div>${release?`<div><dt>最新发行版本</dt><dd>${esc(release.version)}</dd></div>`:''}</dl>${data.phase==='downloading'?`<progress max="100" value="${data.progress}" aria-label="更新下载进度"></progress><p>${data.progress}%</p>`:''}${data.error?`<p class="detail-error" role="alert">${esc(data.error)}</p>`:''}<div class="toolbar"><button type="button" id="softwareCheck" ${['checking','downloading','installing'].includes(data.phase)?'disabled':''}>检查更新</button>${data.phase==='available'?'<button type="button" id="softwareDownload" class="primary">下载更新</button>':''}${data.phase==='ready'?`<button type="button" id="softwareInstall" class="primary" ${data.install_supported?'':'disabled'}>${data.platform==='Windows'?'安装更新并重启 ORH':'打开更新安装包'}</button>`:''}${data.phase==='installing'&&data.platform!=='Windows'?'<button type="button" id="softwareRestart">安装完成，重新启动 ORH</button>':''}<a class="button" href="${esc(release?.page || data.project_url+'/releases/latest')}" target="_blank" rel="noopener">发行页面 ↗</a></div>${data.phase==='ready'&&data.platform==='Windows'?'<p class="muted">安装会重新启动本机 ORH，设备通道将短暂断开。</p>':''}${release?.notes?`<details class="settings-help"><summary>版本更新说明</summary><div class="release-notes">${DOMPurify.sanitize(marked.parse(release.notes))}</div></details>`:''}</section><section class="settings-section"><h2>项目与支持</h2><div class="toolbar"><a class="button" href="${esc(data.project_url)}" target="_blank" rel="noopener">项目主页 ↗</a><a class="button" href="${esc(data.project_url+'/issues')}" target="_blank" rel="noopener">反馈问题 ↗</a></div></section>`;
    const action = (id, endpoint) => {
      const button = root.querySelector(id);
      if (button) button.onclick = async () => {
        button.disabled = true;
        try { await api('/client/software/'+endpoint, {}); if(check())await render(check,target,api); }
        catch(error) { if(check()){root.querySelector('.update-section').insertAdjacentHTML('beforeend',`<p class="detail-error" role="alert">${esc(error.message)}</p>`);button.disabled=false;} }
      };
    };
    action('#softwareCheck','check'); action('#softwareDownload','download'); action('#softwareInstall','install'); action('#softwareRestart','restart');
    if(['checking','downloading'].includes(data.phase)) timer=setTimeout(()=>{if(check())render(check,target,api).catch(error=>{if(check()){root.querySelector('.update-section .badge').textContent='连接暂不可用';root.querySelector('#softwareCheck').disabled=false;root.querySelector('.update-section').insertAdjacentHTML('beforeend',`<p class="detail-error" role="alert">${esc(error.message)}</p>`);}});},1000);
  }
  function reset(){clearTimeout(timer);}
  return {render,reset};
})();
