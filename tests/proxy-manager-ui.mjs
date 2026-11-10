import assert from 'node:assert/strict';
import fs from 'node:fs';
import vm from 'node:vm';
const nodes=new Map(),calls=[],errors=[],notices=[];
let approved=false,reloads=0,pendingResolve;
function node(id){
 if(!nodes.has(id))nodes.set(id,{innerHTML:'',textContent:'',value:'',hidden:false,disabled:false,isConnected:true,open:false,
  classList:{toggle(){}},setAttribute(){},focus(){},showModal(){this.open=true},close(){this.open=false},
  querySelectorAll(){return [node('#workspaceDetailClose'),node('#proxyProfileName'),node('#proxySubscription'),node('#proxyImportKind')]}});
 return nodes.get(id);
}
const profile={id:'abc',name:'机场 <安全>',revision:'r',active:false,subscription:false,nodes:1,groups:1,rules:1,updated:1};
const data={managed:true,consistent:true,engine:{ready:true,privileged:true,revision:'engine',mixed_port:7891,enabled:false},profiles:[profile]};
const more={dataset:{profile:'abc',profileAction:'more'}};
const ctx=vm.createContext({window:{},document:{querySelectorAll:s=>s==='[data-profile]'?[more]:[]},Date,Array,JSON,
 me:{role:'admin'},$:node,esc:s=>String(s??'').replaceAll('<','&lt;'),bytes:String,table:()=>'',empty:String,
 showError:e=>errors.push(e.message),notify:s=>notices.push(s),confirmAction:async()=>approved,requestName:async()=>'',
 withBusy:async(button,key,label,work)=>work(),api:async(path,body)=>{
  calls.push({path,body});
  if(path==='/proxy/manager/import')return new Promise(resolve=>{pendingResolve=resolve});
  if(path==='/proxy/manager/profile')return {ok:true};
  throw Error('Unexpected '+path);
 }});
vm.runInContext(fs.readFileSync('static/proxy-manager.js','utf8'),ctx);
const view=ctx.window.RemoteHubProxyManager;
assert.match(view.markup(data,true),/机场配置/);
await view.bind(data,()=>true,async()=>{reloads++},()=> 'profiles',()=>{});
assert.match(node('#proxyProfiles').innerHTML,/机场 &lt;安全>/);
await more.onclick();
assert.equal(node('#workspaceDetailDialog').open,true);
await node('#proxyDelete').onclick();
assert.equal(node('#workspaceDetailDialog').open,true,'Cancel removal keeps the parent dialog open');
assert.equal(calls.length,0,'Cancel never removes a configuration');
node('#workspaceDetailDialog').close();
node('#proxyImport').onclick();
node('#proxyImportKind').value='url';node('#proxyProfileName').value='new';node('#proxySubscription').value='https://example.invalid/private';
node('#proxyImportForm').oninput();
const submit=node('#proxyImportForm').onsubmit({preventDefault(){}});
assert.equal(node('#workspaceDetailClose').disabled,true,'Cannot dismiss an in-flight mutation');
await node('#workspaceDetailClose').onclick();
assert.equal(node('#workspaceDetailDialog').open,true,'Pending dialog remains open');
await more.onclick();
// A real modal blocks this background click; the busy guard also blocks writes.
await node('#proxyDelete').onclick();
assert.equal(calls.length,1);
pendingResolve({id:'new'});await submit;
assert.equal(reloads,1);assert.equal(view.isDirty(),false);
assert.equal(node('#workspaceDetailDialog').open,false);
assert.equal(node('#workspaceDetailClose').disabled,false);
assert.ok(!notices.some(s=>s.includes('已移除')),'A suppressed removal cannot claim success');
console.log('Proxy manager UI: escaped names, canceled removal, pending mutation lock and honest completion passed.');
