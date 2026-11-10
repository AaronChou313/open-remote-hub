'use strict';
window.RemoteHubProxyNodes=(()=>{
 const cache=new Map(),waiting=new Map(),queue=[],selecting=new Map();
 let active=null,workers=0,batch=null,scope='',search='',sort='default',folds=Object.create(null);
 try{sort=localStorage.getItem('orh-proxy-sort')||sort;const saved=JSON.parse(localStorage.getItem('orh-proxy-folds')||'{}');if(saved&&typeof saved==='object'&&!Array.isArray(saved))Object.assign(folds,saved)}catch{}
 if(!['default','name','delay'].includes(sort))sort='default';
 const builtin=node=>['Direct','Reject','RejectDrop','Pass','PassRule','Compatible','Dns','DNS'].includes(node?.type);
 const guarded=work=>async()=>{try{await work()}catch(error){active?.check()&&showError(error)}};
 function store(){try{localStorage.setItem('orh-proxy-sort',sort);localStorage.setItem('orh-proxy-folds',JSON.stringify(folds))}catch{}}
 function leafNames(names,data){
  const groups=new Map(data.groups.map(g=>[g.name,g])),seen=new Set(),result=[];
  function visit(name){if(seen.has(name))return;seen.add(name);const group=groups.get(name);if(group){group.members.forEach(visit);return}if(Object.hasOwn(data.nodes,name)&&!builtin(data.nodes[name]))result.push(name)}
  names.forEach(visit);return result;
 }
 function ordered(members,data){
  const rows=members.map((name,index)=>({name,index}));
  if(sort==='name')rows.sort((a,b)=>a.name.localeCompare(b.name,'zh-CN',{numeric:true})||a.index-b.index);
  if(sort==='delay')rows.sort((a,b)=>{const x=cache.get(a.name)?.delay,y=cache.get(b.name)?.delay;return (x>0?x:Infinity)-(y>0?y:Infinity)||a.index-b.index});
  return rows;
 }
 function route(data){
  let name=data.mode==='global'?'GLOBAL':data.mode==='direct'?'DIRECT':data.default_policy;
  const path=[],seen=new Set(),groups=new Map(data.groups.map(g=>[g.name,g]));
  while(name&&!seen.has(name)){seen.add(name);path.push(name);name=groups.get(name)?.current}
  return path.join(' → ')||'以规则匹配结果为准';
 }
 function paint(){if(active?.check())active.draw()}
 async function refreshCurrent(expectedScope){
  if(active?.scope!==expectedScope||!active.check())return;
  try{const fresh=await api('/proxy');if(active?.scope!==expectedScope||!active.check()||!fresh.available)return;if(active.data.config_revision&&fresh.config_revision!==active.data.config_revision)return;Object.assign(active.data,fresh);paint()}catch{}
 }
 function cancelPending(){if(batch)batch.cancelled=true;for(const item of queue.splice(0)){if(waiting.get(item.name)===item.promise)waiting.delete(item.name);if(cache.get(item.name))cache.get(item.name).pending=false;item.resolve({cancelled:true})}}
 function pump(){
  if(!active?.check()){cancelPending();return}
  const limit=active?.concurrency||1;
  while(workers<limit&&queue.length){
   const item=queue.shift();workers++;
   (async()=>{
    let result;
    try{result=await api('/proxy/delay',{name:item.name})}catch(error){result=error.status===401?{cancelled:true}:{delay:null,error:error.message}}
    if(result.cancelled){cancelPending();if(cache.get(item.name))cache.get(item.name).pending=false}
    else if(scope===item.scope)cache.set(item.name,{delay:result.delay>0?result.delay:null,tested:true,error:result.error||'',time:Date.now(),pending:false});
    if(waiting.get(item.name)===item.promise)waiting.delete(item.name);
    workers--;item.resolve(result);paint();pump();
   })();
  }
 }
 function testOne(name){
  if(!active?.check())return Promise.resolve({cancelled:true});
  if(waiting.has(name))return waiting.get(name);
  let resolve;const promise=new Promise(r=>{resolve=r});
  waiting.set(name,promise);cache.set(name,{...(cache.get(name)||{}),pending:true});
  queue.push({name,promise,resolve,scope});pump();paint();return promise;
 }
 async function testBatch(names,label){
  if(batch?.running)return;
  const job={running:true,cancelled:false,total:names.length,done:0,failed:0,label,scope};batch=job;paint();
  let index=0;
  async function consume(){while(!job.cancelled&&job.scope===scope&&active?.check()&&index<names.length){const name=names[index++];const result=await testOne(name);if(!result.cancelled){job.done++;if(!(result.delay>0))job.failed++};paint()}}
  await Promise.all(Array.from({length:Math.min(active?.concurrency||1,names.length)},consume));
  job.running=false;if(!job.cancelled)await refreshCurrent(job.scope);paint();
 }
 async function mount(data,check,options={}){
  data.nodes||={};data.groups||=[];
  const nextScope=data.config_revision||options.scope||JSON.stringify(data.groups.map(g=>[g.name,g.members]));
  if(scope!==nextScope){if(batch)batch.cancelled=true;scope=nextScope;cache.clear();batch=null;waiting.clear();for(const item of queue.splice(0))item.resolve({error:'配置已切换'})}
  for(const [name,node] of Object.entries(data.nodes)){
   const old=cache.get(name),time=Date.parse(node.time)||0;
   if(node.tested&&(!old||(!old.pending&&time>old.time)))cache.set(name,{tested:true,delay:node.delay>0?node.delay:null,time,error:node.delay>0?'':'超时或不可达'});
  }
  const admin=me.role==='admin';
  const modeName=value=>({rule:'规则',global:'全局',direct:'直连'}[value]||value);
  $('#proxyNodeControls').innerHTML=`<div class="proxy-node-mode"><span>出站模式</span><div class="proxy-mode-buttons" role="group" aria-label="出站模式">${['rule','global','direct'].map(mode=>`<button data-node-mode="${mode}" aria-pressed="${mode===data.mode}" ${!admin?'disabled':''}>${modeName(mode)}</button>`).join('')}</div></div><p class="proxy-route" id="proxyRoute"></p><div class="proxy-node-toolbar"><label class="sr-only" for="proxySearch">搜索策略组或节点</label><input id="proxySearch" placeholder="搜索策略组或节点"><label for="proxyNodeSort">排序</label><select id="proxyNodeSort"><option value="default">默认排序</option><option value="name">名称排序</option><option value="delay">延迟排序</option></select>${admin?'<button id="proxyTestAll">全部测速</button>':''}<button id="proxyExpandAll">全部展开</button><button id="proxyFoldAll">全部折叠</button></div><div class="proxy-test-status" role="status"><span id="proxyTestProgress"></span><button id="proxyCancelTests" hidden>取消测速</button></div>`;
  active={data,check,scope:nextScope,concurrency:options.concurrency||1,draw};
  function draw(){
   if(!check())return;
   $('#proxyRoute').textContent=(data.mode==='rule'?'规则模式 · 默认路由：':data.mode==='global'?'全局路由：':'直连模式：')+route(data);
   document.querySelectorAll('[data-node-mode]').forEach(button=>button.setAttribute('aria-pressed',String(button.dataset.nodeMode===data.mode)));
   const progress=$('#proxyTestProgress');
   progress.textContent=batch?(batch.running?(batch.cancelled?'正在停止测速… ':`${batch.label} · `):batch.cancelled?'已取消 · ':'测速完成 · ')+`${batch.done}/${batch.total}${batch.failed?' · '+batch.failed+' 个未连通':''}`:'';
   $('#proxyCancelTests').hidden=!batch?.running;$('#proxyCancelTests').disabled=!!batch?.cancelled;
   if($('#proxyTestAll'))$('#proxyTestAll').setAttribute('aria-disabled',String(!!batch?.running));
   const focused=document.activeElement?.dataset||{},focusKey=focused.nodeSelect?['node-select',focused.nodeSelect]:focused.nodeTest?['node-test',focused.nodeTest]:focused.nodeToggle?['node-toggle',focused.nodeToggle]:focused.nodeGroupTest?['node-group-test',focused.nodeGroupTest]:focused.nodeUnfix?['node-unfix',focused.nodeUnfix]:null;
   const q=search.trim().toLowerCase();
   const visible=data.groups.map((group,index)=>({group,index})).filter(({group})=>(group.name+' '+group.members.join(' ')).toLowerCase().includes(q));
   if(data.mode!=='global')visible.sort((a,b)=>Number(a.group.name==='GLOBAL')-Number(b.group.name==='GLOBAL'));
   $('#proxyGroups').innerHTML=visible.length?`<div class="proxy-node-groups">${visible.map(({group,index:g})=>{
    const collapsed=Object.hasOwn(folds,group.name)?!!folds[group.name]:group.name==='GLOBAL'&&data.mode!=='global';
    const rows=ordered(group.members,data).filter(row=>!q||group.name.toLowerCase().includes(q)||row.name.toLowerCase().includes(q));
    const automatic=['URLTest','Fallback'].includes(group.type),count=leafNames(group.members,data).length;
    return `<section class="proxy-node-group"><div class="proxy-node-group-head"><button class="proxy-node-toggle" data-node-toggle="${g}" aria-expanded="${!collapsed}" aria-controls="proxyNodeGroup${g}"><span class="proxy-chevron" aria-hidden="true">${collapsed?'›':'⌄'}</span><span><strong>${esc(group.name)}</strong><small>${esc(group.name==='GLOBAL'?'仅全局模式生效':automatic?(group.fixed?'手动固定':'自动选择'):group.type)} · ${group.members.length} 项</small></span><span class="proxy-group-current">${esc(group.current||'—')}</span></button>${admin?`<div class="toolbar">${automatic&&group.fixed?`<button data-node-unfix="${g}">恢复自动</button>`:''}<button data-node-group-test="${g}" ${!count?'disabled':''} aria-disabled="${!!batch?.running}" aria-label="${esc(group.name)} 整组测速">整组测速</button></div>`:''}</div><div id="proxyNodeGroup${g}" ${collapsed?'hidden':''}><div class="proxy-node-grid">${rows.map(({name,index:m})=>{
     const info=data.nodes[name]||{},value=cache.get(name),selected=name===group.current,pinned=name===group.fixed,key=g+':'+m;
     const delay=value?.pending?'测速中…':value?.delay>0?value.delay+' ms':value?.tested?'超时':'—';
     const child=data.groups.find(x=>x.name===name),subtitle=child?`${child.type} → ${child.current}`:info.type||'节点';
     return `<div class="proxy-node ${selected?'selected':''}"><button class="proxy-node-select" data-node-select="${key}" aria-pressed="${selected}" ${!admin||!group.selectable?'disabled':''} aria-disabled="${selecting.get(group.name)?.scope===scope}" title="${esc(name)}"><span class="proxy-node-name">${esc(name)}</span><span class="proxy-node-meta">${esc(subtitle)}${pinned?' · 已固定':''}</span><span class="proxy-node-value ${value?.tested&&!value.delay&&!value.pending?'unreachable':''}">${selected?'<span aria-hidden="true">✓ </span>':''}${esc(delay)}</span></button>${admin?`<button class="proxy-node-test" data-node-test="${key}" ${info.type?.startsWith('Reject')?'disabled':''} aria-disabled="${!!value?.pending}" aria-label="测速 ${esc(name)}" title="单节点测速">${typeof icon==='function'?icon('refresh'):'↻'}</button>`:''}</div>`;
    }).join('')}</div></div></section>`;
   }).join('')}</div>`:empty('没有匹配的策略组或节点。');
   document.querySelectorAll('[data-node-toggle]').forEach(button=>button.onclick=()=>{const group=data.groups[Number(button.dataset.nodeToggle)];folds[group.name]=button.getAttribute('aria-expanded')==='true';store();draw()});
   document.querySelectorAll('[data-node-group-test]').forEach(button=>button.onclick=guarded(()=>{const group=data.groups[Number(button.dataset.nodeGroupTest)];return testBatch(leafNames(group.members,data),group.name)}));
   document.querySelectorAll('[data-node-select]').forEach(button=>button.onclick=guarded(async()=>{
    const [g,m]=button.dataset.nodeSelect.split(':').map(Number),group=data.groups[g],name=group.members[m];
    if((group.current===name&&(!['URLTest','Fallback'].includes(group.type)||group.fixed===name))||selecting.get(group.name)?.scope===scope)return;
    await select(group,name,false);
   }));
   document.querySelectorAll('[data-node-unfix]').forEach(button=>button.onclick=guarded(()=>select(data.groups[Number(button.dataset.nodeUnfix)],'',true)));
   document.querySelectorAll('[data-node-test]').forEach(button=>button.onclick=guarded(()=>{const [g,m]=button.dataset.nodeTest.split(':').map(Number);return testOne(data.groups[g].members[m])}));
   if(focusKey)(document.querySelector(`[data-${focusKey[0]}="${focusKey[1]}"]`)||document.querySelector(`[data-node-toggle="${focusKey[1].split(':')[0]}"]`))?.focus({preventScroll:true});
  }
  async function select(group,name,unfix){
   if(selecting.get(group.name)?.scope===scope)return;const operation={scope};selecting.set(group.name,operation);draw();
   try{
    let result;
    for(let attempt=0;attempt<2;attempt++){
     try{result=await api('/proxy/control',{action:unfix?'unfix':'select',target:group.name,value:name,revision:group.revision,profile_revision:data.config_revision});break}
     catch(error){if(error.status!==409||attempt)throw error;if(operation.scope!==scope||!check())return;const fresh=await api('/proxy');if(operation.scope!==scope||!check())return;if(data.config_revision&&fresh.config_revision!==data.config_revision)throw Error('机场配置已切换，未重试旧节点操作');const updated=fresh.groups.find(g=>g.name===group.name);if(!updated||(!unfix&&!updated.members.includes(name)))throw Error('策略组已改变，此节点已不存在');Object.assign(group,updated)}
    }
    if(operation.scope!==scope)return;Object.assign(group,result);if(active&&active.scope===operation.scope){const visible=active.data.groups.find(g=>g.name===group.name);if(visible)Object.assign(visible,result)}notify(unfix?'已恢复自动选择':group.name==='GLOBAL'&&data.mode!=='global'?'已设置全局节点，仅全局模式下生效':result.current!==name&&result.fixed===name?'已固定 '+name+'；当前回退到 '+result.current:'已切换 '+group.name+' → '+name);await refreshCurrent(operation.scope);
   }finally{if(selecting.get(group.name)===operation)selecting.delete(group.name);paint()}
  }
  document.querySelectorAll('[data-node-mode]').forEach(button=>button.onclick=guarded(async()=>{
   const mode=button.dataset.nodeMode;if(mode===data.mode)return;
   const requestScope=scope;
   const result=await withBusy(button,'proxy:mode','应用中…',()=>api('/proxy/control',{action:'mode',value:mode,revision:data.revision,profile_revision:data.config_revision}));if(!result)return;
   data.mode=result.mode;data.revision=result.revision;if(active?.scope===requestScope){active.data.mode=result.mode;active.data.revision=result.revision;paint()}
  }));
  $('#proxySearch').value=search;$('#proxySearch').oninput=event=>{search=event.target.value;draw()};
  $('#proxyNodeSort').value=sort;$('#proxyNodeSort').onchange=event=>{sort=event.target.value;store();draw()};
  $('#proxyExpandAll').onclick=()=>{data.groups.forEach(g=>{folds[g.name]=false});store();draw()};
  $('#proxyFoldAll').onclick=()=>{data.groups.forEach(g=>{folds[g.name]=true});store();draw()};
  if(admin)$('#proxyTestAll').onclick=guarded(()=>testBatch(leafNames(Object.keys(data.nodes),data),'全部节点'));
  $('#proxyCancelTests').onclick=()=>{if(batch)batch.cancelled=true;draw()};draw();
 }
 return {mount,leafNames,ordered};
})();
