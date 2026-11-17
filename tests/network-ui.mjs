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
let rustdeskStatus={ready:false,processes:[],connections:0};
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
  return rustdeskStatus;
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
rustdeskStatus={installed:true,ready:true,native_settings:false,device_id:'502852432',accepting:true,online:null,processes:[{pid:42}],connections:null,permanent_password_set:null};
await view.render(()=>true);
assert.equal(nodes.get('#rcSettingsForm').hidden,true);
assert.equal(nodes.get('#rcTemporaryCredential').hidden,true);
assert.equal(nodes.get('#rcDeviceId').value,'502852432');
assert.match(nodes.get('#rcOnline').textContent,/直连接入可用/);
nodes.delete('#rcRoot');
await ctx.RemoteHubLAN.render(()=>true);
assert.equal(lanRefreshes,1);
assert.deepEqual(errors,[]);
console.log('RustDesk and LAN render independently without unrelated module requests.');

// In-page links from backup settings and legacy URLs use the same navigation.
const appSource=fs.readFileSync('static/app.js','utf8');
const routing=appSource.slice(appSource.indexOf("window.addEventListener?.('hashchange'"),appSource.indexOf("\n$('#cloudRegister')",appSource.indexOf("window.addEventListener?.('hashchange'")));
let hashHandler,openedView;
const routeLocation={hash:''};
const routeContext=vm.createContext({window:{addEventListener:(name,handler)=>{hashHandler=handler}},location:routeLocation,
 titles:{lan:'LAN',nodebaby:'NodeBaby',proxy:'Proxy',desktop:'Desktop',mesh:'Mesh'},$:()=>({hidden:false}),switchView:async target=>{openedView=target}});
vm.runInContext(routing,routeContext);
for(const [hash,target] of [['#lan','lan'],['#nodebaby','nodebaby'],['#proxy','proxy'],['#desktop','desktop'],['#network','mesh'],['#remote','lan']]){
 routeLocation.hash=hash;await hashHandler();assert.equal(openedView,target);
}
console.log('Backup-settings links and legacy module routes open the correct standalone page.');

// Enabled Mihomo can reach its built-in installer before a broker exists.
const navigationSource=appSource.slice(appSource.indexOf('async function switchView(target)'),appSource.indexOf('function showLogin()'));
const navigationNodes=new Map();
const navigation=vm.createContext({window:{scrollTo(){}},document:{body:{dataset:{}},querySelectorAll:()=>[]},
 view:'overview',caps:{proxy:false,enabled_modules:['proxy']},VIEW_CAP:{proxy:'proxy'},titles:{proxy:'Proxy',modules:'Modules'},
 me:{host:{system:'Darwin',hostname:'QA'}},renderVersion:0,busy:false,localStorage:{setItem(){}},empty:String,
 $:selector=>{if(!navigationNodes.has(selector))navigationNodes.set(selector,{dataset:{}});return navigationNodes.get(selector)},
 notify(){},refresh(){}});
vm.runInContext(navigationSource,navigation);
await vm.runInContext("switchView('proxy')",navigation);
assert.equal(navigation.view,'proxy');
navigation.view='overview';navigation.caps.enabled_modules=[];
await vm.runInContext("switchView('proxy')",navigation);
assert.equal(navigation.view,'modules');
console.log('Enabled proxy reaches first-use installation, and disabled proxy opens module management.');
