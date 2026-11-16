import assert from 'node:assert/strict';
import fs from 'node:fs';
import vm from 'node:vm';
const nodes=new Map(),calls=[],errors=[];
let lanRefreshes=0,proxyRenders=0;
function element(){
 let html='';
 return {dataset:{},value:'',textContent:'',hidden:false,open:false,isConnected:true,
  classList:{toggle(){}},setAttribute(){},removeAttribute(){},addEventListener(){},reset(){},
  insertAdjacentHTML(){},querySelectorAll(){return []},
  get innerHTML(){return html},set innerHTML(value){html=value;for(const match of value.matchAll(/\bid="([^"]+)"/g))nodes.set('#'+match[1],element())}};
}
for(const id of ['#content','#updated','#outputDialog','#confirmDialog'])nodes.set(id,element());
const document={hidden:false,querySelector:s=>nodes.get(s)||null,querySelectorAll:()=>[]};
const ctx=vm.createContext({window:{addEventListener(){},scrollTo(){}},document,Date,JSON,Object,Promise,
 location:{hostname:'localhost'},copyText:async()=>{},Set,setInterval(){},setTimeout(){},bytes:String,table:()=>'',icon:()=>'',esc:String,empty:String,me:{role:'admin'},
 showError:error=>errors.push(error.message),notify(){},confirmAction:async()=>true,withBusy:async(b,k,l,work)=>work(),
 RemoteHubProxyManager:{canLeave:async()=>true},
 RemoteHubProxy:{render:async(check,target)=>{assert.equal(check(),true);assert.equal(target,'#rcNetworkProxy');proxyRenders++}},
 api:async path=>{
  calls.push(path);
  if(path==='/remote-connect/lan'){lanRefreshes++;return {interfaces:[],devices:[],gateways:[],dns:[],warnings:[]}}
  if(path==='/remote-connect/nodebaby')return {available:false,addresses:[],mappings:[]};
  assert.equal(path,'/remote-connect/rustdesk');
  return {ready:false,processes:[],connections:0};
 }});
for(const file of ['lan','nodebaby','remote-connect']){
 vm.runInContext(fs.readFileSync('static/'+file+'.js','utf8'),ctx);
 if(file==='lan')ctx.RemoteHubLAN=ctx.window.RemoteHubLAN;
 if(file==='nodebaby')ctx.RemoteHubNodeBaby=ctx.window.RemoteHubNodeBaby;
}
const view=ctx.window.RemoteHubRemoteConnect;
await view.render(()=>true);
assert.equal(lanRefreshes,0);
assert.equal(proxyRenders,0);
assert.equal(nodes.has('#rcLAN'),false);
assert.equal(nodes.has('#rcNodeBaby'),false);
assert.equal(nodes.has('#rcNetworkProxy'),false);
assert.equal(nodes.has('#rcOverview'),true);
nodes.delete('#rcRoot');
await ctx.RemoteHubLAN.render(()=>true);
assert.equal(lanRefreshes,1);
assert.deepEqual(errors,[]);
console.log('RustDesk and LAN render independently without unrelated module requests.');
