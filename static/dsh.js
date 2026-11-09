'use strict';
window.RemoteHubDsh=(()=>{
 async function render(check){
  const d=await api('/dsh/status');if(!check())return;
  const url=new URL(location.href);url.port=d.gateway_port;url.pathname='/';url.search='';url.hash='';
  $('#content').innerHTML=`<div class="dsh-toolbar"><span class="badge">DSH ${esc(d.version||'未发现')}</span><span class="muted">${d.running?'已连接本机 Web profile':d.installed?'本机已安装':'未找到本机安装'}</span>${d.running?`<a class="button" href="${esc(url.href)}" target="_blank" rel="noopener">独立窗口 ↗</a>`:`<button id="dshStart" class="primary" ${!d.enabled||!d.installed?'disabled':''}>启动并进入 DSH</button>`}</div>${d.running?`<iframe id="dshFrame" title="DeepSeek Harness 原生 Web" src="${esc(url.href)}" allow="clipboard-write; fullscreen"></iframe>`:empty(!d.enabled?'请在本机配置 ORH_DSH_ENABLED=1 并重启控制台。':d.installed?'使用本机现有配置、插件和会话历史。':'请配置本机 ORH_DSH_BIN；不会自动安装或升级 DSH。')}`;
  if($('#dshStart'))$('#dshStart').onclick=async()=>{
   try{await withBusy($('#dshStart'),'dsh:start','正在启动…',()=>api('/dsh/start',{}));if(check())await render(check)}catch(e){showError(e)}
  };
 }
 return {render};
})();
