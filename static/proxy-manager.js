'use strict';
window.RemoteHubProxyManager=(()=>{
 let dirty=false,operationBusy=false,modalBusy=false;
 const time=value=>value?new Date(value*1000).toLocaleString():'—';
 const guarded=fn=>async event=>{event?.preventDefault();try{await fn(event)}catch(error){showError(error)}};
 function markup(data,admin){
  const engine=data.engine,active=data.profiles.find(row=>row.active);
  const status=data.installation?.running?'安装中 · 请在目标主机授权':!engine.ready?'后台离线':engine.enabled?'代理运行中':engine.privileged?'代理已停止':'预备完成 · 等待主机授权';
  return `<section class="proxy-service"><div><div class="proxy-service-title"><h2>Mihomo</h2><span class="badge ${engine.enabled?'running':''}">${esc(status)}</span></div>${data.network_update_required?'<p class="proxy-error">请更新主机服务以修复 macOS DNS 接管。</p>':''}<p class="muted">${active?esc(active.name):'尚未选择机场配置'}${engine.ready?' · 本机端口 '+engine.mixed_port:''}</p>${engine.error?`<p class="proxy-error">${esc(engine.error)}</p>`:''}${data.installation?.output&&!data.installation.running&&!engine.ready?`<pre class="proxy-error">${esc(data.installation.output)}</pre>`:''}${!data.consistent?'<p class="proxy-error">后台配置与列表不一致，请重新使用所需配置。</p>':''}</div><div class="toolbar">${admin?`${data.install_supported&&(!engine.privileged||data.network_update_required)?'<button id="proxyInstall" '+(data.installation?.running?'disabled':'')+'>'+(data.installation?.running?'安装中…':data.network_update_required?'更新网络接管':'安装 Mihomo')+'</button>':''}${engine.enabled?'<button id="proxyStop" class="danger">停止代理</button>':`<button id="proxyStart" class="primary" ${!engine.ready||!engine.privileged||!active||!data.consistent||data.network_update_required?'disabled':''}>启动代理</button>`}<button id="proxyRestart" ${!engine.revision?'disabled':''}>重启内核</button>`:''}</div></section><div class="proxy-tabs" role="tablist" aria-label="代理管理"><button data-proxy-tab="profiles" role="tab">机场配置</button><button data-proxy-tab="nodes" role="tab">策略与节点</button><button data-proxy-tab="rules" role="tab">路由规则</button><button data-proxy-tab="logs" role="tab">内核日志</button></div><div id="proxyManagedContent"></div>`;
 }
 function modal(title,html){
  if(modalBusy)throw Error('当前配置操作仍在执行，请等待完成。');
  $('#workspaceDetailTitle').textContent=title;$('#workspaceDetailBody').innerHTML=html;
  const dialog=$('#workspaceDetailDialog');
  const close=guarded(async()=>{if(modalBusy)return;if(dirty&&!await confirmAction('放弃未保存的修改','当前编辑内容尚未保存。'))return;dirty=false;dialog.close()});
  $('#workspaceDetailClose').onclick=close;
  dialog.oncancel=event=>{if(modalBusy){event.preventDefault();return}if(dirty){event.preventDefault();close()}};
  dialog.showModal();return dialog;
 }
 async function runBusy(button,key,label,work){
  if(operationBusy)throw Error('上一项代理操作仍在执行，请等待完成。');
  operationBusy=true;
  const dialog=$('#workspaceDetailDialog'),controls=dialog.open?Array.from(dialog.querySelectorAll('input,select,textarea,button')).map(element=>[element,element.disabled]):[];
  modalBusy=dialog.open;controls.forEach(([element])=>{element.disabled=true});
  try{return await withBusy(button,key,label,work)}finally{controls.forEach(([element,disabled])=>{if(element.isConnected)element.disabled=disabled});modalBusy=false;operationBusy=false}
 }
 function isDirty(){return dirty}
 async function canLeave(){if(!dirty)return true;if(!await confirmAction('放弃未保存的修改','当前代理配置尚未保存。'))return false;dirty=false;return true}
 async function bind(data,check,reload,currentTab,onTab){
  const admin=me.role==='admin',engine=data.engine;
  async function service(button,action){
   if(action!=='enable'&&!await confirmAction(action==='disable'?'停止主机代理':'重启 Mihomo 内核',action==='disable'?'使用此代理的连接会中断，主机恢复原有网络路径。':'代理连接会中断并重新建立。'))return;
   await runBusy(button,'proxy:service',action==='enable'?'启动中…':'处理中…',async()=>{const latest=await api('/proxy/manager');return api('/proxy/manager/service',{action,revision:latest.engine.revision,confirm:action})});
   notify(action==='enable'?'代理已启动':action==='disable'?'代理已停止':'内核已重启');if(check())await reload();
  }
  if(admin){
   if($('#proxyStart'))$('#proxyStart').onclick=guarded(()=>service($('#proxyStart'),'enable'));
   if($('#proxyStop'))$('#proxyStop').onclick=guarded(()=>service($('#proxyStop'),'disable'));
   $('#proxyRestart').onclick=guarded(()=>service($('#proxyRestart'),'restart'));
   if($('#proxyInstall'))$('#proxyInstall').onclick=guarded(async()=>{
    await runBusy($('#proxyInstall'),'proxy:install','准备安装…',()=>api('/proxy/manager/install',{}));
    notify('请在目标主机完成管理员授权，安装后可导入订阅并启动代理');
    if(check())await reload();
   });
  }
  if(data.installation?.running){
   $('#proxyManagedContent').innerHTML='<p>正在下载或安装 Mihomo，请在目标主机完成管理员授权。</p>';
   setTimeout(()=>{if(check())reload().catch(showError)},2000);
   return;
  }
  if(!engine.ready){
   $('#proxyManagedContent').innerHTML='<p>安装完成后，在这里导入机场订阅或 Clash / Mihomo 配置。</p>'+(data.install_command?'<details><summary>终端安装命令</summary><pre>'+esc(data.install_command)+'</pre></details>':'');
   return;
  }
  async function profiles(){
   $('#proxyManagedContent').innerHTML=`<div class="work-toolbar"><label class="sr-only" for="proxyProfileSearch">搜索机场配置</label><input id="proxyProfileSearch" placeholder="搜索机场配置">${admin?'<button id="proxyImport" class="primary">导入配置</button>':''}</div><div id="proxyProfiles"></div>`;
   const draw=()=>{
    const query=$('#proxyProfileSearch').value.trim().toLowerCase(),rows=data.profiles.filter(x=>x.name.toLowerCase().includes(query));
    $('#proxyProfiles').innerHTML=rows.length?`<div class="proxy-profiles">${rows.map(row=>{
     const usage=row.usage||{},used=(usage.upload||0)+(usage.download||0);
     return `<article class="proxy-profile"><div class="proxy-group-title"><h3>${esc(row.name)}</h3>${row.active?'<span class="badge running">当前配置</span>':''}</div><p>${row.nodes} 节点 · ${row.groups} 策略组 · ${row.rules} 规则</p>${usage.total?`<p>已用 ${bytes(used)} / ${bytes(usage.total)}${usage.expire?' · 到期 '+time(usage.expire):''}</p>`:''}<p class="muted">${row.subscription?'订阅':'本地配置'} · 更新于 ${time(row.updated)}</p><div class="toolbar">${admin?`<button data-profile="${row.id}" data-profile-action="activate" ${row.active&&data.consistent?'disabled':''}>${row.active&&data.consistent?'已使用':'使用配置'}</button>${row.subscription?`<button data-profile="${row.id}" data-profile-action="update">更新订阅</button>`:''}<button data-profile="${row.id}" data-profile-action="edit">编辑</button><button data-profile="${row.id}" data-profile-action="more">更多</button>`:''}</div></article>`;
    }).join('')}</div>`:empty(query?'没有匹配的配置。':'导入机场订阅 URL 或 Clash / Mihomo YAML，即可开始使用。');
    document.querySelectorAll('[data-profile]').forEach(button=>button.onclick=guarded(()=>operate(button,data.profiles.find(x=>x.id===button.dataset.profile),button.dataset.profileAction)));
   };
   $('#proxyProfileSearch').oninput=draw;draw();
   if(admin)$('#proxyImport').onclick=()=>{
    const dialog=modal('导入机场配置',`<form id="proxyImportForm"><label for="proxyProfileName">配置名称</label><input id="proxyProfileName" required maxlength="120" autocomplete="off"><label for="proxyImportKind">导入方式</label><select id="proxyImportKind"><option value="url">订阅 URL</option><option value="file">YAML 文件</option></select><div id="proxyURLField"><label for="proxySubscription">订阅 URL</label><input id="proxySubscription" type="password" autocomplete="off" placeholder="https://…"><small class="muted">选择机场提供的 Clash / Mihomo 格式订阅。</small></div><div id="proxyFileField" hidden><label for="proxyYAMLFile">YAML 文件</label><input id="proxyYAMLFile" type="file" accept=".yaml,.yml,.json"></div><p id="proxyFormError" class="proxy-error" role="alert"></p><div class="dialog-actions"><button type="submit" id="proxyImportSubmit" class="primary">导入并检查</button></div></form>`);
    $('#proxyImportKind').onchange=()=>{const kind=$('#proxyImportKind').value;$('#proxyURLField').hidden=kind!=='url';$('#proxyFileField').hidden=kind!=='file'};
    $('#proxyImportForm').oninput=()=>{dirty=true};
    $('#proxyImportForm').onsubmit=async event=>{
     event.preventDefault();const kind=$('#proxyImportKind').value,body={name:$('#proxyProfileName').value,url:kind==='url'?$('#proxySubscription').value.trim():'',text:''};
     try{
      if(kind==='file'){const file=$('#proxyYAMLFile').files[0];if(!file)throw Error('请选择配置文件');if(file.size>3*1024*1024)throw Error('配置最大为 3 MiB');body.text=await file.text()}
      await runBusy($('#proxyImportSubmit'),'proxy:import','下载并检查中…',()=>api('/proxy/manager/import',body));dirty=false;dialog.close();notify('已导入配置，点击「使用配置」即可选用');if(check())await reload();
     }catch(error){$('#proxyFormError').textContent=error.message}
    };
    $('#proxyProfileName').focus();
   };
  }
  async function operate(button,row,action){
   if(action==='edit'){
    const result=await runBusy(button,'proxy:read','读取中…',()=>api('/proxy/manager/profile/'+row.id));if(!check())return;
    const settings=result.settings;
    const dialog=modal('配置选项 · '+row.name,`<form id="proxyEditForm" class="settings-form"><label class="switch-row"><span>启用 IPv6</span><input type="checkbox" id="proxyIPv6" role="switch" ${settings.ipv6?'checked':''}></label><label>日志级别<select id="proxyLogLevel">${[['silent','静默'],['error','错误'],['warning','警告'],['info','常规'],['debug','调试']].map(([key,name])=>`<option value="${key}" ${settings.log_level===key?'selected':''}>${name}</option>`).join('')}</select></label><fieldset><legend>DNS</legend><label class="switch-row"><span>启用 DNS 解析</span><input type="checkbox" id="proxyDNSEnabled" role="switch" ${settings.dns_enabled?'checked':''}></label><label>解析模式<select id="proxyDNSMode"><option value="fake-ip" ${settings.dns_mode==='fake-ip'?'selected':''}>Fake IP</option><option value="redir-host" ${settings.dns_mode==='redir-host'?'selected':''}>真实 IP</option></select></label><label>DNS 服务器</label><div id="proxyNameservers"></div><label>备用 DNS</label><div id="proxyFallback"></div></fieldset><p id="proxyFormError" class="proxy-error" role="alert"></p><div class="dialog-actions"><button id="proxySaveConfig" type="submit" class="primary">保存配置</button></div></form>`);
    const nameservers=RemoteHubFormControls.list('#proxyNameservers',settings.nameservers,{label:'DNS 服务器',placeholder:'例如 https://dns.alidns.com/dns-query',onChange:()=>{dirty=true;}});
    const fallback=RemoteHubFormControls.list('#proxyFallback',settings.fallback,{label:'备用 DNS',placeholder:'例如 1.1.1.1',onChange:()=>{dirty=true;}});
    $('#proxyEditForm').oninput=()=>{dirty=true;};
    $('#proxyEditForm').onsubmit=async event=>{
     event.preventDefault();
     const settings={ipv6:$('#proxyIPv6').checked,log_level:$('#proxyLogLevel').value,dns_enabled:$('#proxyDNSEnabled').checked,dns_mode:$('#proxyDNSMode').value,nameservers:nameservers.values(),fallback:fallback.values()};
     try{await runBusy($('#proxySaveConfig'),'proxy:profile','保存中…',()=>api('/proxy/manager/profile',{action:'settings',id:row.id,revision:result.revision,settings}));dirty=false;dialog.close();notify('配置已保存');if(check())await reload()}catch(error){$('#proxyFormError').textContent=error.message}
    };return;
   }
   if(action==='more'){
    const dialog=modal(row.name,`<div class="toolbar"><button id="proxyRename">重命名</button><button id="proxySubscriptionEdit">更换订阅 URL</button><a class="button" href="/api/proxy/manager/profile/${row.id}/download" download>导出 YAML</a><button id="proxyDelete" class="danger" ${row.active&&engine.enabled?'disabled title="请先停止代理"':''}>移除配置</button></div><form id="proxySubscriptionForm" hidden><label for="proxyNewSubscription">新的订阅 URL</label><input type="password" id="proxyNewSubscription" autocomplete="off" required placeholder="https://…"><p class="muted">仅替换订阅地址，更新订阅后才会加载新内容。</p><p id="proxyFormError" class="proxy-error" role="alert"></p><div class="dialog-actions"><button type="submit" id="proxySubscriptionSave">保存订阅地址</button></div></form>`);
    $('#proxyRename').onclick=guarded(async()=>{if(dirty&&!await canLeave())return;const name=await requestName('重命名配置',row.name,'保存',120);if(!name||name===row.name)return;await runBusy($('#proxyRename'),'proxy:profile','保存中…',()=>api('/proxy/manager/profile',{action:'rename',id:row.id,revision:row.revision,name}));dialog.close();if(check())await reload()});
    $('#proxySubscriptionEdit').onclick=()=>{$('#proxySubscriptionForm').hidden=false;$('#proxyNewSubscription').focus()};
    $('#proxyNewSubscription').oninput=()=>{dirty=true};
    $('#proxySubscriptionForm').onsubmit=async event=>{event.preventDefault();try{await runBusy($('#proxySubscriptionSave'),'proxy:profile','保存中…',()=>api('/proxy/manager/profile',{action:'subscription',id:row.id,revision:row.revision,url:$('#proxyNewSubscription').value.trim()}));dirty=false;dialog.close();notify('订阅地址已保存');if(check())await reload()}catch(error){$('#proxyFormError').textContent=error.message}};
    $('#proxyDelete').onclick=guarded(async()=>{if(await operate($('#proxyDelete'),row,'delete')){dirty=false;if(dialog.open)dialog.close()}});return;
   }
   if(action==='delete'&&!await confirmAction('移除 '+row.name,'从配置列表移除，主机保留恢复副本。'))return;
   await runBusy(button,'proxy:profile','处理中…',()=>api('/proxy/manager/profile',{action,id:row.id,revision:row.revision,confirm:row.name}));notify(action==='activate'?'已使用此配置':action==='update'?'订阅已更新':'配置已移除');if(check())await reload();return true;
  }
  async function selectTab(tab){
   if(!check())return;onTab(tab);
   document.querySelectorAll('[data-proxy-tab]').forEach(button=>{const active=button.dataset.proxyTab===tab;button.classList.toggle('active',active);button.setAttribute('aria-selected',String(active));button.setAttribute('tabindex',active?'0':'-1');button.id='proxyTab-'+button.dataset.proxyTab;button.setAttribute('aria-controls',button.dataset.proxyTab==='nodes'?'proxyRuntime':'proxyManagedContent')});
   $('#proxyRuntime').hidden=tab!=='nodes';$('#proxyManagedContent').hidden=tab==='nodes';for(const id of ['#proxyRuntime','#proxyManagedContent']){$(id).setAttribute('role','tabpanel');$(id).setAttribute('aria-labelledby','proxyTab-'+tab)}
   if(tab==='profiles'){await profiles();return}
   if(tab==='nodes')return;
   $('#proxyManagedContent').innerHTML=empty('读取中…');
   const result=await api('/proxy/manager/'+tab);if(!check()||!$('#proxyManagedContent')||currentTab()!==tab)return;
   if(tab==='logs')$('#proxyManagedContent').innerHTML='<pre class="proxy-log" id="proxyLogText"></pre>';
   if(tab==='logs')$('#proxyLogText').textContent=result.text||'暂无日志。';
   else $('#proxyManagedContent').innerHTML=`<p class="muted">${result.total} 条规则，最多显示前 2000 条。</p><label class="sr-only" for="proxyRuleSearch">筛选规则</label><input id="proxyRuleSearch" placeholder="筛选规则、目标或策略组"><div id="proxyRuleRows"></div>`;
   if(tab==='rules'){const draw=()=>{const q=$('#proxyRuleSearch').value.toLowerCase();$('#proxyRuleRows').innerHTML=table(['类型','目标','策略'],result.entries.filter(r=>[r.type,r.payload,r.proxy].join(' ').toLowerCase().includes(q)).map(r=>`<tr><td>${esc(r.type)}</td><td class="file-name">${esc(r.payload||'—')}</td><td>${esc(r.proxy)}</td></tr>`))};$('#proxyRuleSearch').oninput=draw;draw()}
  }
  const tabs=Array.from(document.querySelectorAll('[data-proxy-tab]'));
  tabs.forEach((button,index)=>{
   button.onclick=guarded(()=>selectTab(button.dataset.proxyTab));
   button.onkeydown=async event=>{const target={ArrowRight:(index+1)%tabs.length,ArrowLeft:(index+tabs.length-1)%tabs.length,Home:0,End:tabs.length-1}[event.key];if(target===undefined)return;event.preventDefault();try{await selectTab(tabs[target].dataset.proxyTab);tabs[target].focus()}catch(error){showError(error)}};
  });
  await selectTab(currentTab());
 }
 return {markup,bind,isDirty,canLeave};
})();
