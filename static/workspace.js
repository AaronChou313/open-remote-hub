'use strict';
window.RemoteHubWorkspace=(()=>{
 const state={root:'',path:'',selected:null,text:null,dirty:false,project:null,environment:null,showHidden:localStorage.getItem('orh-files-hidden')==='true',sort:'name',order:'asc',projectQuery:'',projectScroll:0};
 let current=()=>true,selectionVersion=0,environmentSelection=0,preparedList=null,projectOpener=null;
 const query=o=>new URLSearchParams(o).toString();
 const join=(a,b)=>[a,b].filter(Boolean).join('/');
 const endpoint=(name,extra={})=>'/files/'+name+'?'+query({root:state.root,path:state.path,show_hidden:state.showHidden,sort:state.sort,order:state.order,...extra});
 const admin=()=>me.role==='admin';
 function failure(e){showError(e);if($('#filePreviewDialog').open){$('#filePreviewError').textContent=e.message;$('#filePreviewError').hidden=false;$('#filePreviewError').scrollIntoView({block:'nearest'})}}
 function guarded(fn){return async e=>{e?.preventDefault();try{await fn(e)}catch(err){failure(err)}}}
 function bind(id,fn){const el=$(id);if(el)el.onclick=guarded(fn)}
 async function canLeave(){if(window.RemoteHubUploads?.isUploading()){notify('请先完成或取消文件上传');return false}if(!state.dirty)return true;if(await confirmAction('放弃未保存的编辑？','尚未保存的文件修改将丢失。')){state.dirty=false;return true}return false}
 async function closeFilePreview(){
  if(!await canLeave())return;
  selectionVersion++;
  state.selected=null;state.text=null;
  $('#filePreviewDialog').close();
 }
 function showFilePreview(){
  const dialog=$('#filePreviewDialog');
  $('#filePreviewError').hidden=true;
  dialog.oncancel=guarded(async event=>{event.preventDefault();await closeFilePreview()});
  $('#filePreviewClose').onclick=guarded(closeFilePreview);
  if(!dialog.open)dialog.showModal();
 }
 function showWorkspaceDetail(title,body){
  $('#workspaceDetailTitle').textContent=title;
  $('#workspaceDetailBody').innerHTML=body;
  const dialog=$('#workspaceDetailDialog');
  $('#workspaceDetailClose').onclick=()=>dialog.close();
  if(!dialog.open)dialog.showModal();
 }
 function form(title,fields,submit='保存'){
  const d=$('#workspaceDialog');if(d.open)return Promise.resolve(null);
  $('#workspaceDialogTitle').textContent=title;
  $('#workspaceFields').innerHTML=fields.map(f=>`<label for="wf-${f.name}">${esc(f.label)}</label>${f.options?`<select id="wf-${f.name}" name="${f.name}">${f.options.map(([v,l])=>`<option value="${esc(v)}">${esc(l)}</option>`).join('')}</select>`:f.multiline?`<textarea id="wf-${f.name}" name="${f.name}" ${f.required===false?'':'required'}>${esc(f.value||'')}</textarea>`:`<input id="wf-${f.name}" name="${f.name}" value="${esc(f.value||'')}" ${f.required===false?'':'required'} maxlength="4096" autocomplete="off">`}`).join('');
  $('#workspaceSubmit').textContent=submit;d.returnValue='cancel';d.showModal();$('#workspaceFields input, #workspaceFields select, #workspaceFields textarea')?.focus();
  return new Promise(resolve=>{d.onclose=()=>resolve(d.returnValue==='save'?Object.fromEntries(new FormData($('#workspaceForm'))):null);$('#workspaceForm').onsubmit=e=>{e.preventDefault();d.close('save')};$('#workspaceCancel').onclick=()=>d.close('cancel')});
 }
 async function rerender(){await refresh()}
 async function folder(path){if(!await canLeave())return;preparedList=await api('/files/list?'+query({root:state.root,path,show_hidden:state.showHidden,sort:state.sort,order:state.order}));state.dirty=false;state.text=null;state.selected=null;state.path=path;await rerender()}
 async function files(check){
  current=check;
  if(state.dirty)return;
  const config=await api('/files/roots'),roots=config.roots;if(!check())return;
  if(!roots.length){$('#content').innerHTML=empty('尚未授权文件目录。请在本机 .env 中设置 ORH_FILE_ROOTS。');return}
  if(!roots.some(x=>x.id===state.root)){state.root=config.default?.root||roots[0].id;state.path=config.default?.path||'';state.selected=null}
  const d=preparedList&&preparedList.root===state.root&&preparedList.path===state.path?preparedList:await api(endpoint('list'));preparedList=null;if(!check())return;
  $('#content').innerHTML=`<div class="work-toolbar"><label class="sr-only" for="fileRoot">授权目录</label><select id="fileRoot">${roots.map(r=>`<option value="${r.id}" ${r.id===state.root?'selected':''}>${esc(r.path)}</option>`).join('')}</select><form id="filePathForm"><label class="sr-only" for="filePath">相对路径</label><input id="filePath" value="${esc(state.path)}" placeholder="根目录下的相对路径" autocomplete="off"><button>前往</button></form><button id="fileHome">主目录</button><button id="fileUp" ${!state.path?'disabled':''}>上一级</button></div><div class="work-toolbar"><form id="fileSearchForm"><label class="sr-only" for="fileSearch">搜索文件名</label><input id="fileSearch" placeholder="在当前目录搜索文件名" maxlength="100"><button>搜索</button></form>${admin()?`<button id="fileUpload" ${d.read_only?'disabled':''}>${icon('upload')}上传文件</button><input id="filePicker" type="file" multiple hidden><button id="fileUploadFolder" ${d.read_only?'disabled':''}>${icon('folder')}上传文件夹</button><input id="folderPicker" type="file" webkitdirectory multiple hidden><button id="fileMkdir" ${d.read_only?'disabled':''}>${icon('mkdir')}新建目录</button><button id="fileTrash" ${d.read_only?'disabled':''}>${icon('restore')}回收记录</button><button id="fileTerminal">${icon('terminal')}终端 ${icon('external')}</button><a class="button" href="${esc(d.editor_url)}" title="通过 Remote SSH 在当前设备的 VS Code 中打开">${icon('code')}用 VS Code 打开</a><button id="fileProject">添加为项目</button>`:''}<span id="uploadStatus" role="status">${d.read_only?'系统目录 · 只读':''}</span></div><div class="file-filters"><label class="check-label"><input id="fileHidden" type="checkbox" ${state.showHidden?'checked':''}>显示隐藏文件</label><label for="fileSort">排序</label><select id="fileSort"><option value="name">名称</option><option value="modified">修改时间</option><option value="size">大小</option><option value="kind">类型</option></select><button id="fileOrder">${state.order==='asc'?'升序':'降序'}</button></div><div id="fileResults">${fileTable(d.entries)}</div>${d.next_offset!==null?'<button id="fileMore">加载更多</button>':''}${d.truncated?'<p class="muted">目录超过 10000 项，仅展示前 10000 项。请缩小范围。</p>':''}`;
  $('#fileRoot').onchange=guarded(async e=>{if(!await canLeave()){e.target.value=state.root;return}state.root=e.target.value;await folder('')});
  $('#filePathForm').onsubmit=guarded(()=>folder($('#filePath').value.trim().replace(/^\//,'')));
  bind('#fileUp',()=>folder(state.path.split('/').slice(0,-1).join('/')));
  $('#fileSearchForm').onsubmit=guarded(async()=>{const result=await api(endpoint('search',{q:$('#fileSearch').value}));if(!check())return;$('#fileResults').innerHTML=fileTable(result.entries,true)+(result.truncated?'<p class="muted">结果或扫描范围已达到上限，请缩小目录。</p>':'');$('#fileMore')?.remove();wireFiles(result.entries,true)});
  let entries=d.entries,offset=d.next_offset;
  bind('#fileMore',async()=>{const next=await api(endpoint('list',{offset}));if(!check())return;entries=entries.concat(next.entries);offset=next.next_offset;$('#fileResults').innerHTML=fileTable(entries);wireFiles(entries);if(offset===null)$('#fileMore')?.remove()});
  wireFiles(entries);
  $('#fileSort').value=state.sort;
  $('#fileHidden').onchange=guarded(async e=>{if(!await canLeave()){e.target.checked=state.showHidden;return}state.showHidden=e.target.checked;localStorage.setItem('orh-files-hidden',state.showHidden);preparedList=null;await rerender()});
  $('#fileSort').onchange=guarded(async e=>{if(!await canLeave())return;state.sort=e.target.value;preparedList=null;await rerender()});
  bind('#fileOrder',async()=>{if(!await canLeave())return;state.order=state.order==='asc'?'desc':'asc';preparedList=null;await rerender()});
  bind('#fileHome',async()=>{if(!config.default)throw Error('主目录不在授权范围');if(!await canLeave())return;state.root=config.default.root;await folder(config.default.path)});

  if(admin()){
   bind('#fileMkdir',async()=>{const n=await requestName('新建目录','','创建',255);if(n){await api('/files/operation',{root:state.root,path:join(state.path,n),action:'mkdir'});await folder(state.path)}});
   for(const [button,picker,folderUpload] of [['#fileUpload','#filePicker',false],['#fileUploadFolder','#folderPicker',true]]){
    bind(button,()=>$(picker).click());
    $(picker).onchange=guarded(async event=>{
     const files=Array.from(event.target.files);event.target.value='';
     const root=state.root,path=state.path;
     await withBusy($(button),'file:upload','上传中…',()=>window.RemoteHubUploads.start({files,root,path,folder:folderUpload,onRefresh:()=>folder(path)}));
    });
   }
   bind('#fileTrash',async()=>{
    if(!await canLeave())return;
    const rows=(await api(endpoint('trash'))).entries;
    $('#fileDetail').innerHTML=panel('当前目录的回收记录',rows.length?table(['原名称','大小','操作'],rows.map((f,i)=>`<tr><td class="file-name">${esc(f.original_name)}</td><td>${bytes(f.size)}</td><td><button data-restore="${i}">恢复</button></td></tr>`)):empty('此目录暂无回收记录。'));
    showFilePreview();
    document.querySelectorAll('[data-restore]').forEach(b=>b.onclick=guarded(async()=>{const row=rows[Number(b.dataset.restore)];await withBusy(b,'file:restore','恢复中…',()=>api('/files/restore',{root:state.root,path:state.path,name:row.name,revision:row.revision,confirm:row.original_name}));state.selected=null;$('#filePreviewDialog').close();await rerender();notify('已恢复，未覆盖其他文件')}));
   });
   bind('#fileTerminal',()=>terminal(state.root,state.path));
   bind('#fileProject',()=>addProject(state.root,state.path));
  }
  if(state.selected){const found=entries.find(x=>join(state.path,x.name)===state.selected.path);if(found)await selectFile(found,state.selected.path,d.read_only,false)}
 }
 function fileTable(entries,search=false){return entries.length?table(['名称','大小','修改时间','操作'],entries.map((f,i)=>`<tr><td class="file-name"><button class="file-link" data-file="${i}" ${f.protected?'disabled':''}>${icon(f.kind==='directory'?'folder':f.kind==='link'?'link':/\.(png|jpe?g|gif|webp)$/i.test(f.name)?'image':/\.(py|js|ts|json|html|css|sh|toml|yaml|yml)$/i.test(f.name)?'code':'file')} ${esc(search?f.path:f.name)}</button>${f.protected?`<span class="muted">${esc(f.protection_reason||'受保护')}</span>`:''}</td><td>${f.kind==='directory'?'—':bytes(f.size)}</td><td>${new Date(f.modified*1000).toLocaleString()}</td><td>${!f.protected?`<button data-file-menu="${i}" aria-label="${esc(f.name)} 操作">操作</button>`:'—'}</td></tr>`)):empty('此目录没有可显示的文件。')}
 function wireFiles(entries,search=false){
  document.querySelectorAll('[data-file]').forEach(b=>b.onclick=guarded(async()=>{const f=entries[Number(b.dataset.file)],path=search?f.path:join(state.path,f.name);if(f.kind==='directory')await folder(path);else await selectFile(f,path)}));
  document.querySelectorAll('[data-file-menu]').forEach(b=>b.onclick=guarded(async()=>{const f=entries[Number(b.dataset.fileMenu)];await fileMenu(f,search?f.path:join(state.path,f.name))}));
 }
 async function fileMenu(file,path){
  if(!await canLeave())return;
  state.selected={...file,path};
  const dialog=$('#fileActionDialog');
  $('#fileActionTitle').textContent=file.name;
  $('#fileActionPath').textContent=path;
  const operations=admin()?(file.read_only?['copy']:['copy','move','rename','delete']):[];
  const labels={copy:'复制到…',move:'移动到…',rename:'重命名',delete:'移入回收目录'};
  $('#fileActionButtons').innerHTML=`<button data-folder-action="open">${file.kind==='directory'?'打开文件夹':'查看文件'}</button>${operations.map(action=>`<button data-folder-action="${action}" ${action==='delete'?'class="danger"':''}>${esc(labels[action])}</button>`).join('')}`;
  $('#fileActionCancel').onclick=()=>dialog.close();
  dialog.showModal();
  document.querySelectorAll('[data-folder-action]').forEach(button=>button.onclick=guarded(async()=>{
   const action=button.dataset.folderAction;dialog.close();
   if(action==='open'){if(file.kind==='directory')await folder(path);else await selectFile(file,path);return}
   await fileOperation(action);
  }));
 }
 async function selectFile(f,path,readOnly=f.read_only||false,scroll=true){
  if(state.selected?.path!==path&&!await canLeave())return;
  const token=++selectionVersion,check=current;let loaded=null;
  let detail='';
  if(f.kind==='file'){
   if(/\.(png|jpe?g|gif|webp)$/i.test(f.name))detail=`<img class="file-preview" alt="${esc(f.name)}" src="/api${endpoint('download',{path})}">`;
   else try{loaded=await api(endpoint('text',{path}));detail=`<label for="fileEditor">UTF-8 文本 · ${bytes(f.size)}</label><textarea id="fileEditor" class="file-editor" spellcheck="false" ${!admin()||readOnly?'readonly':''}>${esc(loaded.text)}</textarea>${admin()&&!readOnly?`<div class="toolbar"><button id="fileSave" class="primary">${icon('save')}保存修改</button><span id="fileDirty" class="muted">已加载</span></div>`:''}`}catch(e){detail=`<p class="muted">${esc(e.message)}</p>`}
  }
  if(token!==selectionVersion||!check())return;
  state.selected={...f,path};state.dirty=false;state.text=loaded;
  $('#fileDetail').innerHTML=panel(path,`<div class="file-detail-body"><div class="toolbar">${f.kind==='file'?`<a class="button" href="/api${endpoint('download',{path})}">${icon('download')}下载</a>`:''}${admin()&&!readOnly?'<button data-file-op="copy">复制</button><button data-file-op="move">移动</button><button data-file-op="rename">重命名</button><button class="danger" data-file-op="delete">删除</button>':''}<button id="fileClose">关闭详情</button></div>${detail}</div>`);
  showFilePreview();
  $('#fileEditor')?.addEventListener('input',()=>{state.dirty=true;$('#fileDirty').textContent='未保存'});
  bind('#fileClose',closeFilePreview);
  bind('#fileSave',async()=>{if(!state.dirty)return;await withBusy($('#fileSave'),'file:save','保存中…',async()=>{const editor=$('#fileEditor'),submitted=editor.value;const result=await api('/files/text',{root:state.root,path,text:submitted,revision:state.text.revision,confirm:path});if(state.selected?.path===path&&$('#fileEditor')===editor){state.text.revision=result.revision;state.selected.revision=result.entry_revision||result.revision;state.dirty=editor.value!==submitted;$('#fileDirty').textContent=state.dirty?'仍有未保存修改':'已保存'}notify('文件已保存')})});
  document.querySelectorAll('[data-file-op]').forEach(b=>b.onclick=guarded(()=>fileOperation(b.dataset.fileOp,b)));
 }
 async function fileOperation(action,button){
  if(!await canLeave())return;
  const f=state.selected;let destination='';
  if(action!=='delete'){
   const n=await requestName({copy:'复制到（授权根目录内相对路径）',move:'移动到（授权根目录内相对路径）',rename:'重命名'}[action],action==='rename'?f.name:join(state.path,f.name+'-copy'),'继续',4096);if(!n)return;
   destination=action==='rename'?join(f.path.split('/').slice(0,-1).join('/'),n):n;
  }
  if(action==='delete'&&!await confirmAction('删除 '+f.path,'移入所在目录的私有回收目录。目录内含受保护文件时会拒绝。'))return;
  await withBusy(button,'file:operation','处理中…',()=>api('/files/operation',{root:state.root,path:f.path,revision:f.revision,action,destination,confirm:f.path}));state.dirty=false;state.selected=null;$('#filePreviewDialog').close();await rerender();notify('操作完成');
 }
 async function terminal(root,path,preferred=''){
  const sessions=(await api('/zellij')).sessions;
  const values=await form('打开目录终端',[{name:'session',label:'选择已有会话，或新建',options:[['','新建会话'],...sessions.map(s=>[s.name,s.name+(s.status==='running'?'':'（已退出）')])]},{name:'name',label:'新会话名称',value:preferred,required:false}],'进入终端 ↗');if(!values)return;
  const name=values.session||values.name;if(!name)throw Error('请选择会话或填写新会话名称');
  const url='/terminal/open/'+encodeURIComponent(name)+'?'+query({root,path});
  const tab=window.open(url,'_blank');if(!tab)throw Error('请允许弹出终端标签页后重试');tab.opener=null;
 }
 async function addProject(root,path){const values=await form('添加本地项目',[{name:'name',label:'项目名称',value:path.split('/').at(-1)||'项目'},{name:'path',label:'根目录下的项目路径',value:path,required:false}],'添加项目');if(!values)return;const result=await api('/projects',{root,path:values.path,name:values.name});state.project=result.id;switchView('projects')}
 async function projects(check){
  current=check;
  const list=(await api('/projects')).projects.sort((a,b)=>a.name.localeCompare(b.name,'zh-CN',{numeric:true,sensitivity:'base'})||a.path.localeCompare(b.path));if(!check())return;
  $('#content').innerHTML=`<div id="projectOverview"><div class="work-toolbar"><label class="sr-only" for="projectSearch">搜索项目</label><input id="projectSearch" placeholder="搜索项目名称或路径">${admin()?`<button class="primary" id="addProject">${icon('plus')}添加项目</button>`:''}</div><div id="projectList"></div></div><div id="projectDetail" hidden></div>`;
  function draw(q=''){
   const filtered=list.filter(p=>(p.name+' '+p.path).toLowerCase().includes(q.toLowerCase()));
   $('#projectList').innerHTML=filtered.length?`<div class="project-grid">${filtered.map((p,i)=>`<article class="project-card"><div><h2>${esc(p.name)}</h2><p class="mono">${esc(p.path||'/')}</p><p>${p.available?esc(p.stack.join(' · ')||'未发现常见技术栈标记'):'目录不可用或不再授权'}</p></div><div class="toolbar"><button data-project="${i}" ${!p.available?'disabled':''}>打开项目</button>${admin()?`<button data-remove-project="${i}">${p.discovered?'隐藏项目':'移除记录'}</button>`:''}</div></article>`).join('')}</div>`:empty(list.length?'没有匹配的项目。':'从文件管理器打开一个项目目录，或添加现有目录。');
   document.querySelectorAll('[data-project]').forEach(b=>b.onclick=guarded(async()=>{projectOpener=b;state.projectScroll=window.scrollY||0;state.project=filtered[Number(b.dataset.project)].id;await withBusy(b,'project:open','打开中…',()=>showProject(state.project,check))}));
   document.querySelectorAll('[data-remove-project]').forEach(b=>b.onclick=guarded(async()=>{const p=filtered[Number(b.dataset.removeProject)];if(!await confirmAction('移除项目记录 '+p.name,'仅从控制台移除记录；保留磁盘文件、现有终端和后台任务。'))return;await withBusy(b,'project:'+p.id,'移除中…',()=>api('/projects/'+p.id,{action:'remove',revision:p.revision,confirm:p.id}));if(state.project===p.id)state.project=null;await rerender()}));
  }
  $('#projectSearch').value=state.projectQuery;draw(state.projectQuery);$('#projectSearch').oninput=e=>{state.projectQuery=e.target.value;draw(state.projectQuery)};
  bind('#addProject',async()=>{const roots=(await api('/files/roots')).roots;if(!roots.length)throw Error('请先授权文件目录');const v=await form('添加本地项目',[{name:'root',label:'授权根目录',options:roots.map(r=>[r.id,r.path])},{name:'path',label:'根目录下的相对路径',value:'',required:false},{name:'name',label:'项目名称'}],'添加项目');if(v){const p=await api('/projects',v);state.project=p.id;await rerender()}});
  if(state.project&&list.some(x=>x.id===state.project&&x.available))await showProject(state.project,check);
 }
 async function showProject(id,check){
  if(state.project!==id||!check())return;
  const p=await api('/projects/'+id);if(!check()||state.project!==id)return;
  $('#projectDetail').innerHTML='<button id="projectBack" class="detail-back">返回项目列表</button>'+panel(p.name,`<div class="file-detail-body"><p class="mono">${esc(p.absolute_path)}</p><div class="workspace-summary"><span>${esc(p.stack.join(' · ')||'未检测到技术栈')}</span><span>${esc(p.environment_markers.join(' · '))}</span><span>环境：${esc(p.environment?.name||'未绑定')}</span></div><div class="toolbar"><button id="projectFiles">打开文件</button>${admin()?`<button id="projectTerminal">${icon('terminal')}终端 ${icon('external')}</button><a class="button" href="${esc(p.editor_url)}" title="通过 Remote SSH 在当前设备的 VS Code 中打开">${icon('code')}用 VS Code 打开</a><button id="projectBind">绑定环境</button>`:''}<button id="projectEnvironment" ${!p.environment?'disabled':''}>环境详情</button></div><h3>Git</h3><div class="workspace-tabs">${[['status','状态'],['branches','分支'],['commits','最近提交'],['diff','工作区 Diff'],['staged','暂存区 Diff']].map(([k,l])=>`<button data-git="${k}" ${!p.git?'disabled':''}>${l}</button>`).join('')}</div><pre id="projectGit">${p.git?'选择一项查看仓库信息。':'此目录不是 Git 仓库根目录。'}</pre><h3>预设任务</h3>${p.presets.length?table(['任务','实际命令 / 项目脚本','操作'],p.presets.map((t,i)=>`<tr><td>${esc(t.label)}</td><td class="file-name"><code>${esc(JSON.stringify(t.argv))}</code><br><small>${esc(t.description)}</small></td><td>${admin()?`<button data-preset="${i}">运行</button>`:''}</td></tr>`)): '<p class="muted">未发现受支持的预设。可在原生终端中运行其他命令。</p>'}<div class="toolbar"><button id="projectTasks">查看服务与日志</button></div></div>`);
  const firstOpen=$('#projectDetail').hidden;
  $('#projectOverview').hidden=true;$('#projectDetail').hidden=false;
  if(firstOpen){window.scrollTo?.(0,0);$('#projectBack').focus()}
  bind('#projectBack',()=>{
   state.project=null;$('#projectDetail').hidden=true;$('#projectOverview').hidden=false;
   window.scrollTo?.(0,state.projectScroll);
   if(projectOpener?.isConnected)projectOpener.focus();else document.querySelector('[data-project]')?.focus();
  });
  bind('#projectFiles',()=>{state.root=p.root;state.path=p.path;state.selected=null;switchView('files')});
  bind('#projectTasks',()=>switchView('services'));
  bind('#projectEnvironment',()=>{state.environment=p.environment?.id;switchView('environments')});
  bind('#projectTerminal',async()=>{
   const sessions=(await api('/zellij')).sessions;
   const v=await form('项目终端',[{name:'session',label:'已有会话（保留原目录）或新建',options:[['','新建会话'],...sessions.map(s=>[s.name,s.name])]},{name:'name',label:'新会话名称',value:p.session||'',required:false}],'进入终端 ↗');if(!v)return;
   const name=v.session||v.name;if(!name)throw Error('请选择会话或填写名称');
   const tab=window.open('/terminal/open/'+encodeURIComponent(name)+'?'+query({project:p.id,revision:p.revision}),'_blank');if(!tab)throw Error('请允许打开终端标签页');tab.opener=null;
  });
  bind('#projectBind',async()=>{
   const envs=(await api('/environments')).environments;
   const v=await form('绑定项目环境',[{name:'environment',label:'环境',options:[['','解除绑定'],...envs.map(e=>[e.id,e.name+' · '+e.path])]}],'保存绑定');if(!v)return;
   await api('/projects/'+p.id,{action:'environment',revision:p.revision,environment:v.environment,confirm:p.id});await showProject(p.id,check);
  });
  document.querySelectorAll('[data-git]').forEach(b=>b.onclick=guarded(async()=>{await withBusy(b,'git:'+p.id,'读取中…',async()=>{const r=await api('/projects/'+p.id+'/git?'+query({kind:b.dataset.git}));if(check()&&state.project===p.id)$('#projectGit').textContent=(r.output||'无变更')+(r.truncated?'\n[输出已截断]':'')})}));
  document.querySelectorAll('[data-preset]').forEach(b=>b.onclick=guarded(async()=>{const t=p.presets[Number(b.dataset.preset)];if(!await confirmAction('运行 '+p.name+' · '+t.label,`目录：${p.absolute_path}\n参数：${JSON.stringify(t.argv)}\n项目脚本：${t.description}\n此任务可执行项目代码，以当前用户权限运行。`))return;await withBusy(b,'project:run:'+p.id,'启动中…',()=>api('/projects/'+p.id,{action:'run',revision:p.revision,confirm:p.id,preset:t.key,digest:t.digest}));notify('任务已启动，可在本地服务查看日志');await showProject(p.id,check)}));
 }
 async function environments(check){
  current=check;
  const d=await api('/environments');if(!check())return;
  $('#content').innerHTML=panel('主机开发工具',table(['工具','版本','路径'],d.tools.map(t=>`<tr><td>${esc(t.name)}</td><td>${esc(t.available?t.version:'未发现')}</td><td class="file-name mono">${esc(t.path||'—')}</td></tr>`)))+`<div class="work-toolbar"><button id="softwareInventory">已安装软件</button>${admin()?`<button id="createEnvironment">${icon('plus')}创建项目 venv</button>`:''}</div>`+panel('项目与已检测环境',d.environments.length?table(['环境','类型 / 版本','路径','操作'],d.environments.map((e,i)=>`<tr><td>${esc(e.name)}</td><td>${esc(e.kind)} · ${esc(e.version||'')}</td><td class="file-name mono">${esc(e.path)}</td><td><button data-environment="${i}">查看依赖</button></td></tr>`)):empty('尚未发现环境。添加项目后会检测其 .venv 和 venv。'));
  bind('#softwareInventory',async e=>{await withBusy(e.target,'software:query','查询中…',async()=>{const r=await api('/environments/software');if(check()){output(r.manager,r.output+(r.truncated?'\n[输出已截断]':''))}})});
  async function inspect(id){
   const selection=++environmentSelection;const e=await api('/environments/'+id);if(!check()||selection!==environmentSelection)return;
   showWorkspaceDetail(e.name,`<div class="file-detail-body"><p class="mono">${esc(e.path)}</p><div class="dependency-list">${e.packages.length?table(['依赖','版本'],e.packages.map(p=>`<tr><td>${esc(p.name)}</td><td>${esc(p.version)}</td></tr>`)):empty('此环境没有可读取的安装包元数据。')}</div>${e.truncated?'<p class="muted">依赖列表已截断。</p>':''}</div>`);
   state.environment=null;
  }
  document.querySelectorAll('[data-environment]').forEach(b=>b.onclick=guarded(()=>withBusy(b,'environment:read','读取中…',()=>inspect(d.environments[Number(b.dataset.environment)].id))));
  bind('#createEnvironment',async()=>{
   const projects=(await api('/projects')).projects.filter(p=>p.available);
   if(!projects.length)throw Error('请先添加一个可用项目');
   const v=await form('创建全新项目 venv',[{name:'project',label:'目标项目',options:projects.map(p=>[p.id,p.name+' · '+p.path])},{name:'name',label:'环境目录',options:[['.venv','.venv'],['venv','venv']]}],'查看创建计划');if(!v)return;
   const plan=await api('/environments/plan',v);
   if(!await confirmAction('确认创建 Python 环境',`目标：${plan.absolute_path}\n命令：${JSON.stringify(plan.argv)}\n${plan.effect}`))return;
   await withBusy($('#createEnvironment'),'environment:create','创建中…',()=>api('/environments/create',{...v,confirm:v.project,digest:plan.digest}));notify('环境已创建；可在项目中绑定');await rerender();
  });
  if(state.environment&&d.environments.some(e=>e.id===state.environment))await inspect(state.environment);
 }
 function reset(){
  selectionVersion++;environmentSelection++;
  window.RemoteHubUploads?.reset();
  state.dirty=false;state.text=null;state.selected=null;
  $('#filePreviewDialog').close();$('#workspaceDetailDialog').close();
  $('#fileDetail').replaceChildren();$('#workspaceDetailBody').replaceChildren();
  $('#filePreviewError').textContent='';$('#filePreviewError').hidden=true;
 }
 return {files,projects,environments,canLeave,reset,isDirty:()=>state.dirty||!!window.RemoteHubUploads?.isUploading(),form,terminal,state,addProject};
})();
