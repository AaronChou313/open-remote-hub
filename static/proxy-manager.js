'use strict';
window.RemoteHubProxyManager=(()=>{
 let dirty=false,operationBusy=false,modalBusy=false;
 const time=value=>value?new Date(value*1000).toLocaleString():'—';
 const guarded=fn=>async event=>{event?.preventDefault();try{await fn(event)}catch(error){showError(error)}};
 function markup(data,admin){
  const engine=data.engine,active=data.profiles.find(row=>row.active);
  const status=!engine.ready?'后台离线':engine.enabled?'代理运行中':engine.privileged?'代理已停止':'预备完成 · 等待主机授权';
  return `<section class="proxy-service"><div><div class="proxy-service-title"><h2>Mihomo</h2><span class="badge ${engine.enabled?'running':''}">${esc(status)}</span></div><p class="muted">${active?esc(active.name):'尚未选择机场配置'}${engine.ready?' · 本机端口 '+engine.mixed_port:''}</p>${engine.error?`<p class="proxy-error">${esc(engine.error)}</p>`:''}${!data.consistent?'<p class="proxy-error">后台配置与列表不一致，请重新使用所需配置。</p>':''}</div><div class="toolbar">${admin?`${!engine.privileged?'<button id="proxyInstall">完成主机授权</button>':''}${engine.enabled?'<button id="proxyStop" class="danger">停止代理</button>':`<button id="proxyStart" class="primary" ${!engine.ready||!engine.privileged||!active||!data.consistent?'disabled':''}>启动代理</button>`}<button id="proxyRestart" ${!engine.revision?'disabled':''}>重启内核</button>`:''}</div></section><div class="proxy-tabs" role="tablist" aria-label="代理管理"><button data-proxy-tab="profiles" role="tab">机场配置</button><button data-proxy-tab="nodes" role="tab">策略与节点</button><button data-proxy-tab="rules" role="tab">路由规则</button><button data-proxy-tab="logs" role="tab">内核日志</button></div><div id="proxyManagedContent"></div>`;
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
   await runBusy(button,'proxy:service',action==='enable'?'启动中…':'处理中…',()=>api('/proxy/manager/service',{action,revision:engine.revision,confirm:action}));
   notify(action==='enable'?'代理已启动':action==='disable'?'代理已停止':'内核已重启');if(check())await reload();
  }
  if(admin){
   if($('#proxyStart'))$('#proxyStart').onclick=guarded(()=>service($('#proxyStart'),'enable'));
   if($('#proxyStop'))$('#proxyStop').onclick=guarded(()=>service($('#proxyStop'),'disable'));
   $('#proxyRestart').onclick=guarded(()=>service($('#proxyRestart'),'restart'));
   if($('#proxyInstall'))$('#proxyInstall').onclick=()=>modal('一次性主机授权',`<p>在目标主机终端运行下列命令。只安装 RemoteHub 的专用后台服务，首次安装保持代理关闭，不会关闭 Clash。</p><pre>${esc(data.install_command||'请参考 README 中的代理安装步骤。')}</pre><p>完成后刷新本页。日常操作和后续机场配置都在这里完成。</p>`);
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
    const dialog=modal('导入机场配置',`<form id="proxyImportForm"><label for="proxyProfileName">配置名称</label><input id="proxyProfileName" required maxlength="120" autocomplete="off"><label for="proxyImportKind">导入方式</label><select id="proxyImportKind"><option value="url">订阅 URL</option><option value="file">YAML 文件</option><option value="text">粘贴 YAML</option></select><div id="proxyURLField"><label for="proxySubscription">订阅 URL</label><input id="proxySubscription" type="password" autocomplete="off" placeholder="https://…"><small class="muted">选择机场提供的 Clash / Mihomo 格式订阅。</small></div><div id="proxyFileField" hidden><label for="proxyYAMLFile">YAML 文件</label><input id="proxyYAMLFile" type="file" accept=".yaml,.yml,.json"></div><div id="proxyTextField" hidden><label for="proxyYAML">YAML 内容</label><textarea id="proxyYAML" class="file-editor" spellcheck="false"></textarea></div><p id="proxyFormError" class="proxy-error" role="alert"></p><div class="dialog-actions"><button type="submit" id="proxyImportSubmit" class="primary">导入并检查</button></div></form>`);
    $('#proxyImportKind').onchange=()=>{const kind=$('#proxyImportKind').value;$('#proxyURLField').hidden=kind!=='url';$('#proxyFileField').hidden=kind!=='file';$('#proxyTextField').hidden=kind!=='text'};
    $('#proxyImportForm').oninput=()=>{dirty=true};
    $('#proxyImportForm').onsubmit=async event=>{
     event.preventDefault();const kind=$('#proxyImportKind').value,body={name:$('#proxyProfileName').value,url:kind==='url'?$('#proxySubscription').value.trim():'',text:kind==='text'?$('#proxyYAML').value:''};
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
    const dialog=modal('编辑 · '+row.name,`<form id="proxyEditForm"><p>编辑节点、规则、DNS 和策略组。监听端口与 TUN 路由由 RemoteHub 管理。配置含凭据，请妥善保管。</p><label class="sr-only" for="proxyConfigText">配置 YAML</label><textarea id="proxyConfigText" class="file-editor" spellcheck="false"></textarea><p id="proxyFormError" class="proxy-error" role="alert"></p><div class="dialog-actions"><a class="button" href="/api/proxy/manager/profile/${row.id}/download" download>导出 YAML</a><button id="proxySaveConfig" type="submit" class="primary">检查并保存</button></div></form>`);
    $('#proxyConfigText').value=result.text;$('#proxyConfigText').oninput=()=>{dirty=$('#proxyConfigText').value!==result.text};
    $('#proxyEditForm').onsubmit=async event=>{
     event.preventDefault();if(!dirty)return;
     if(!await confirmAction('保存 '+row.name,row.active?'保存后立即应用，现有连接可能重新建立。':'检查并替换此配置的 YAML。'))return;
     try{await runBusy($('#proxySaveConfig'),'proxy:profile','检查并保存中…',()=>api('/proxy/manager/profile',{action:'save',id:row.id,revision:result.revision,confirm:row.name,text:$('#proxyConfigText').value}));dirty=false;dialog.close();notify('配置已保存');if(check())await reload()}catch(error){$('#proxyFormError').textContent=error.message}
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
   if((action==='delete'||(action==='activate'&&engine.enabled)||(action==='update'&&row.active&&engine.enabled))&&!await confirmAction(action==='delete'?'移除 '+row.name:'应用 '+row.name,action==='delete'?'从配置列表移除，主机保留恢复副本。':'这会更新当前代理配置，现有连接可能重新建立。'))return;
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
