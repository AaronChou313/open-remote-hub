import fs from 'node:fs';
import vm from 'node:vm';
import assert from 'node:assert/strict';
const nodes=new Map(),calls=[],storage=new Map(),errors=[];
let resolveDelay,delayMode='immediate';
function node(id){if(!nodes.has(id))nodes.set(id,{innerHTML:'',value:'',textContent:'',disabled:false,hidden:false,attrs:{},dataset:{},classList:{toggle(){}},focus(){},setAttribute(k,v){this.attrs[k]=v},getAttribute(k){return this.attrs[k]}});return nodes.get(id)}
const selections=[{dataset:{nodeSelect:'0:0'}},{dataset:{nodeSelect:'0:1'}}],tests=[{dataset:{nodeTest:'0:0'}}],toggles=[{dataset:{nodeToggle:'0'},getAttribute:()=> 'true'}],batches=[{dataset:{nodeGroupTest:'0'}}],modes=['rule','global','direct'].map(mode=>({dataset:{nodeMode:mode},setAttribute(){}}));
const snapshot={mode:'rule',revision:'mode',default_policy:'Main <unsafe>',groups:[{name:'Main <unsafe>',type:'Selector',current:'n1',members:['n2','n1','Auto','DIRECT'],selectable:true,revision:'g0'},{name:'Auto',type:'URLTest',current:'n1',fixed:'',members:['n1','n2'],selectable:true,revision:'g1'}],nodes:{n2:{type:'Vless',tested:true,delay:80},n1:{type:'Vless',tested:true,delay:20},Auto:{type:'URLTest'},DIRECT:{type:'Direct'},'PASS-RULE':{type:'PassRule'}}};
const lists={'[data-node-select]':selections,'[data-node-test]':tests,'[data-node-toggle]':toggles,'[data-node-group-test]':batches,'[data-node-mode]':modes};
const context=vm.createContext({window:{},document:{activeElement:null,querySelectorAll:s=>lists[s]||[],querySelector:()=>null},Date,Number,JSON,Map,Set,Object,Array,Infinity,Promise,me:{role:'admin'},localStorage:{getItem:k=>storage.get(k),setItem:(k,v)=>storage.set(k,v)},$:node,icon:()=>'',esc:s=>String(s??'').replaceAll('<','&lt;').replaceAll('>','&gt;'),empty:String,notify(){},showError:e=>errors.push(e.message),confirmAction:()=>{throw Error('Ordinary proxy actions must not request confirmation')},withBusy:async(button,key,label,work)=>work(),api:async(path,body)=>{
 calls.push({path,body});
 if(path==='/proxy/control')return body.action==='mode'?{mode:body.value,revision:'mode-next'}:{current:body.value,revision:'group-next',fixed:''};
 if(path==='/proxy/delay'){if(delayMode==='pending')return new Promise(r=>{resolveDelay=r});return {delay:body.name==='n1'?25:50}}
 throw Error('Unexpected request '+path);
}});
vm.runInContext(fs.readFileSync('static/proxy-nodes.js','utf8'),context);
const view=context.window.RemoteHubProxyNodes;
assert.deepEqual(Array.from(view.leafNames(['Main <unsafe>','Auto','n1'],snapshot)),['n2','n1'],'Nested groups deduplicate physical nodes and omit builtins');
await view.mount(snapshot,()=>true,{scope:'fixture',concurrency:1});
assert.match(node('#proxyGroups').innerHTML,/Main &lt;unsafe&gt;/);assert.ok(!node('#proxyGroups').innerHTML.includes('<select'));
assert.match(node('#proxyRoute').textContent,/Main <unsafe> → n1/);
await selections[0].onclick();
assert.equal(calls.filter(c=>c.path==='/proxy/control').length,1);
assert.equal(calls[0].body.value,'n2');assert.ok(!('confirm' in calls[0].body));
await modes[1].onclick();assert.equal(snapshot.mode,'global');
node('#proxyNodeSort').value='name';node('#proxyNodeSort').onchange({target:{value:'name'}});
assert.deepEqual(Array.from(view.ordered(['n2','n1'],snapshot),x=>x.name),['n1','n2']);
node('#proxyNodeSort').onchange({target:{value:'delay'}});
assert.deepEqual(Array.from(view.ordered(['n2','n1'],snapshot),x=>x.name),['n1','n2']);
await tests[0].onclick();assert.match(node('#proxyGroups').innerHTML,/50 ms/);
await toggles[0].onclick();assert.equal(JSON.parse(storage.get('orh-proxy-folds'))['Main <unsafe>'],true);
await node('#proxyExpandAll').onclick();assert.equal(JSON.parse(storage.get('orh-proxy-folds'))['Main <unsafe>'],false);
calls.length=0;await batches[0].onclick();
assert.deepEqual(calls.filter(c=>c.path==='/proxy/delay').map(c=>c.body.name),['n2','n1']);
assert.match(node('#proxyTestProgress').textContent,/测速完成 · 2\/2/);
calls.length=0;await node('#proxyTestAll').onclick();assert.equal(calls.filter(c=>c.path==='/proxy/delay').length,2);
delayMode='pending';calls.length=0;
const job=node('#proxyTestAll').onclick();await Promise.resolve();
node('#proxyCancelTests').onclick();resolveDelay({delay:100});await job;
assert.equal(calls.length,1,'Cancel prevents remaining queued tests');assert.match(node('#proxyTestProgress').textContent,/已取消/);
assert.deepEqual(errors,[]);
console.log('Proxy nodes: one-click selection/mode, folding, name/delay sorting, deduplicated group/all tests and cancellation passed.');
// Leaving/logout cancels future tests after the already-running request finishes.
let visible=true;await view.mount(snapshot,()=>visible,{scope:'logout-scope',concurrency:1});
calls.length=0;const logoutJob=node('#proxyTestAll').onclick();await Promise.resolve();visible=false;resolveDelay({delay:11});await logoutJob;
assert.equal(calls.length,1,'Logout cannot schedule remaining node probes');
// A late 409 must not retry an old click against a new profile.
let rejectSelection;let selectionPending=false;
context.api=async(path,body)=>{calls.push({path,body});if(path==='/proxy/control')return new Promise((resolve,reject)=>{rejectSelection=reject;selectionPending=true});throw Error('Stale operation retried unexpectedly')};
visible=true;await view.mount(snapshot,()=>visible,{scope:'old-profile',concurrency:1});calls.length=0;
const selection=selections[1].onclick();await Promise.resolve();assert.equal(selectionPending,true);
const replacement=structuredClone(snapshot);await view.mount(replacement,()=>true,{scope:'new-profile',concurrency:1});
const stale=Error('changed');stale.status=409;rejectSelection(stale);await selection;
assert.equal(calls.length,1,'Profile switch prevents stale retry');
assert.ok(!node('#proxyGroups').innerHTML.includes('aria-disabled="true"'),'Late completion releases only its own busy state');
console.log('Proxy nodes lifecycle: logout cancellation and cross-profile stale selection guard passed.');
