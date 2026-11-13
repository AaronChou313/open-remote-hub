'use strict';
window.RemoteHubProxy=(()=>{
 let tab='profiles';
 async function render(check,target='#content'){
  const container=$(target);
  const [data,manager]=await Promise.all([api('/proxy'),api('/proxy/manager')]);if(!check())return;
  const admin=me.role==='admin';
  const system=data.system;
  const systemRows=(system.proxies||[]).map(row=>`<span>${esc(row.name)} <strong>${row.enabled?'已开启':'关闭'}</strong></span>`).join('');
  const systemText=system.vpn?`${esc(system.vpn.name)} VPN · ${system.vpn.state==='Connected'?'已连接':esc(system.vpn.state)}`:esc(system.note||'未发现 Clash VPN 连接');
  const systemPanel=panel('系统网络',`<div class="proxy-system"><span>${systemText}</span>${systemRows}</div>`);
  const managerPanel=manager.managed?RemoteHubProxyManager.markup(manager,admin):'';
  const bindManager=()=>manager.managed?RemoteHubProxyManager.bind(manager,check,()=>render(check,target),()=>tab,value=>{tab=value}):undefined;
  if(!data.available){container.innerHTML=managerPanel+'<div id="proxyRuntime">'+systemPanel+empty(esc(data.error))+'</div>';await bindManager();return}
  container.innerHTML=managerPanel+`<div id="proxyRuntime"><div class="proxy-heading"><div><strong>${manager.managed?'Mihomo':'Clash / Mihomo'} ${esc(data.version||'')}</strong><span class="proxy-runtime-state">TUN ${data.tun_enabled?'已启用':'未启用'}</span></div><button id="proxyConnections">活跃连接 ${data.connection_count}</button></div><details class="proxy-network-details"><summary>网络与资源${system.vpn?' · '+systemText:''}</summary><div class="proxy-totals"><span>内存 <strong>${bytes(data.memory)}</strong></span><span>累计上传 <strong>${bytes(data.upload_total)}</strong></span><span>累计下载 <strong>${bytes(data.download_total)}</strong></span></div>${systemPanel}</details><div id="proxyNodeControls"></div><div id="proxyGroups"></div></div>`;
  const guarded=fn=>async()=>{try{await fn()}catch(error){if(check())showError(error)}};
  await RemoteHubProxyNodes.mount(data,check,{scope:manager.managed?manager.engine.config_revision:undefined,concurrency:manager.managed&&!(manager.engine.network_revision>=2)?1:4});
  async function showConnections(){
   const result=await withBusy($('#proxyConnections'),'proxy:connections','读取中…',()=>api('/proxy/connections'));if(!check())return;
   $('#workspaceDetailTitle').textContent='活跃连接 · '+result.total+' 条';
   const canClose=admin&&manager.managed;
   $('#workspaceDetailBody').innerHTML=result.entries.length?`<div class="toolbar"><p class="muted">按累计传输量排序，最多显示 50 条。</p>${canClose?'<button id="proxyCloseAll" class="danger">断开全部连接</button>':''}</div>`+table(['目标','程序 / 规则','路由','上传 / 下载',...(canClose?['操作']:[])],result.entries.map(row=>`<tr><td class="file-name">${esc(row.host||'—')}:${esc(row.port||'')}<br><small>${esc(row.network||'')}</small></td><td>${esc(row.process||'—')}<br><small>${esc(row.rule||'')}</small></td><td>${esc(row.chains.slice().reverse().join(' → '))}</td><td>${bytes(row.upload)} / ${bytes(row.download)}</td>${canClose?`<td>${row.id?`<button data-proxy-close="${esc(row.id)}">断开</button>`:''}</td>`:''}</tr>`)):empty('当前没有活跃连接。');
   const dialog=$('#workspaceDetailDialog');$('#workspaceDetailClose').onclick=()=>dialog.close();dialog.oncancel=null;if(!dialog.open)dialog.showModal();
   async function close(button,id){if(!await confirmAction(id?'断开此连接':'断开全部代理连接',id?'此连接正在传输的数据会中断，应用可能自动重连。':'Mihomo 管理的所有连接会中断，包括下载、SSH 和其他正在传输的数据。'))return;await withBusy(button,'proxy:connections-close','断开中…',()=>api('/proxy/manager/connections/close',{id,confirm:id||'all'}));if(check()&&dialog.open)await showConnections()}
   if(canClose&&$('#proxyCloseAll'))$('#proxyCloseAll').onclick=guarded(()=>close($('#proxyCloseAll'),''));
   document.querySelectorAll('[data-proxy-close]').forEach(button=>button.onclick=guarded(()=>close(button,button.dataset.proxyClose)));
  }
  $('#proxyConnections').onclick=guarded(showConnections);
  await bindManager();
 }
 return {render};
})();
