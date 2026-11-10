'use strict';
window.RemoteHubProxy=(()=>{
 let searchText='';
 const modeName=value=>({rule:'规则',global:'全局',direct:'直连'}[value]||value||'—');
 async function render(check){
  const data=await api('/proxy');if(!check())return;
  const admin=me.role==='admin';
  const system=data.system;
  const systemRows=(system.proxies||[]).map(row=>`<span>${esc(row.name)} <strong>${row.enabled?'已开启':'关闭'}</strong></span>`).join('');
  const systemText=system.vpn?`${esc(system.vpn.name)} VPN · ${system.vpn.state==='Connected'?'已连接':esc(system.vpn.state)}`:esc(system.note||'未发现 Clash VPN 连接');
  const systemPanel=panel('系统网络',`<div class="proxy-system"><span>${systemText}</span>${systemRows}</div>`);
  if(!data.available){$('#content').innerHTML=systemPanel+empty(esc(data.error));return}
  $('#content').innerHTML=`<div class="proxy-heading"><div><strong>Clash / Mihomo ${esc(data.version||'')}</strong><p class="muted">${modeName(data.mode)}模式 · TUN ${data.tun_enabled?'已启用':'未启用'} · 更新于 ${new Date(data.time*1000).toLocaleTimeString()}</p></div><button id="proxyConnections">活跃连接 ${data.connection_count}</button></div><div class="proxy-totals"><span>内存 <strong>${bytes(data.memory)}</strong></span><span>累计上传 <strong>${bytes(data.upload_total)}</strong></span><span>累计下载 <strong>${bytes(data.download_total)}</strong></span></div>${systemPanel}<div class="work-toolbar"><label for="proxyMode">出站模式</label><select id="proxyMode" ${!admin?'disabled':''}>${['rule','global','direct'].map(mode=>`<option value="${mode}" ${mode===data.mode?'selected':''}>${modeName(mode)}</option>`).join('')}</select>${admin?'<button id="proxyApplyMode">应用模式</button>':''}<label class="sr-only" for="proxySearch">搜索策略组或节点</label><input id="proxySearch" placeholder="搜索策略组或节点"></div><div id="proxyGroups"></div>`;
  const guarded=fn=>async()=>{try{await fn()}catch(error){if(check())showError(error)}};
  async function apply(button,body,title,message){
   if(!await confirmAction(title,message))return;
   if(!check())return;
   await withBusy(button,'proxy:control','应用中…',()=>api('/proxy/control',body));
   notify('Clash 状态已更新');if(check())await render(check);
  }
  if(admin)$('#proxyApplyMode').onclick=guarded(async()=>{
   const value=$('#proxyMode').value;if(value===data.mode)return;
   await apply($('#proxyApplyMode'),{action:'mode',value,revision:data.revision,confirm:'mode'},'切换 Clash 出站模式',`从${modeName(data.mode)}改为${modeName(value)}。这会改变主机后续连接的路由方式。`);
  });
  function draw(){
   const q=searchText.toLowerCase();
   const groups=data.groups.filter(group=>(group.name+' '+group.members.join(' ')).toLowerCase().includes(q));
   $('#proxyGroups').innerHTML=groups.length?`<div class="proxy-groups">${groups.map((group,i)=>`<article class="proxy-group"><div class="proxy-group-title"><h2>${esc(group.name)}</h2><span class="badge">${esc(group.type)}</span></div><p class="proxy-current">当前 <strong>${esc(group.current||'—')}</strong></p><label class="sr-only" for="proxyGroup${i}">${esc(group.name)} 节点</label><select id="proxyGroup${i}" ${!admin||!group.selectable?'disabled':''}>${group.members.map(name=>`<option value="${esc(name)}" ${name===group.current?'selected':''}>${esc(name)}</option>`).join('')}</select><div class="toolbar">${admin&&group.selectable?`<button data-proxy-select="${i}">切换节点</button>`:''}${admin?`<button data-proxy-delay="${i}">测试延迟</button>`:''}<span id="proxyDelay${i}" class="muted" role="status"></span></div></article>`).join('')}</div>`:empty('没有匹配的策略组或节点。');
   document.querySelectorAll('[data-proxy-select]').forEach(button=>button.onclick=guarded(async()=>{
    const i=Number(button.dataset.proxySelect),group=groups[i],value=$('#proxyGroup'+i).value;
    if(value===group.current)return;
    await apply(button,{action:'select',target:group.name,value,revision:group.revision,confirm:group.name},'切换 '+group.name,`从「${group.current}」改为「${value}」。使用该策略组的新连接将采用此选择。`);
   }));
   document.querySelectorAll('[data-proxy-delay]').forEach(button=>button.onclick=guarded(async()=>{
    const i=Number(button.dataset.proxyDelay),name=$('#proxyGroup'+i).value||groups[i].current,target=$('#proxyDelay'+i);
    const result=await withBusy(button,'proxy:delay:'+name,'测速中…',()=>api('/proxy/delay',{name}));
    if(result&&check()&&$('#proxyDelay'+i)===target)target.textContent=Number.isFinite(result.delay)?result.delay+' ms':'未返回延迟';
   }));
  }
  $('#proxySearch').value=searchText;$('#proxySearch').oninput=event=>{searchText=event.target.value;draw()};draw();
  $('#proxyConnections').onclick=guarded(async()=>{
   const result=await withBusy($('#proxyConnections'),'proxy:connections','读取中…',()=>api('/proxy/connections'));if(!check())return;
   $('#workspaceDetailTitle').textContent='活跃连接 · '+result.total+' 条';
   $('#workspaceDetailBody').innerHTML=result.entries.length?`<p class="muted">按累计传输量排序，最多显示 50 条。</p>`+table(['目标','程序 / 规则','路由','上传 / 下载'],result.entries.map(row=>`<tr><td class="file-name">${esc(row.host||'—')}:${esc(row.port||'')}<br><small>${esc(row.network||'')}</small></td><td>${esc(row.process||'—')}<br><small>${esc(row.rule||'')}</small></td><td>${esc(row.chains.slice().reverse().join(' → '))}</td><td>${bytes(row.upload)} / ${bytes(row.download)}</td></tr>`)):empty('当前没有活跃连接。');
   const dialog=$('#workspaceDetailDialog');$('#workspaceDetailClose').onclick=()=>dialog.close();dialog.showModal();
  });
 }
 return {render};
})();
