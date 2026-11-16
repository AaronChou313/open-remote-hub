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
 setInterval(){},setTimeout(){},icon:()=>'',esc:String,empty:String,me:{role:'admin'},
 showError:error=>errors.push(error.message),notify(){},confirmAction:async()=>true,withBusy:async(b,k,l,work)=>work(),
 RemoteHubLAN:{markup:()=>'<section id="rcLAN"></section>',mount(){},refresh:async()=>{lanRefreshes++}},
 RemoteHubNodeBaby:{markup:()=>'<section id="rcNodeBaby"></section>',mount(){},update(){}},
 RemoteHubProxyManager:{canLeave:async()=>true},
 RemoteHubProxy:{render:async(check,target)=>{assert.equal(check(),true);assert.equal(target,'#rcNetworkProxy');proxyRenders++}},
 api:async path=>{
  calls.push(path);assert.equal(path,'/remote-connect');
  return {rustdesk:{ready:false,processes:[],connections:0},tailscale:{available:true,reachable:true,state:'Running',peers:[],device:{addresses:[]},health:[]},mesh:{available:true},lan_urls:[]};
 }});
vm.runInContext(fs.readFileSync('static/remote-connect.js','utf8'),ctx);
const view=ctx.window.RemoteHubRemoteConnect;
await view.render(()=>true);
assert.equal(lanRefreshes,1);
assert.equal(proxyRenders,0);
assert.equal(nodes.has('#rcProxyState'),false,'Removed summary cards stay absent in the real DOM');
view.openTab('proxy');
await view.render(()=>true);
assert.equal(proxyRenders,1);
assert.deepEqual(errors,[]);
console.log('Network UI renders with real absent elements and opens the proxy tab.');
