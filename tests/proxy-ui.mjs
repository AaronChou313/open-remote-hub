import fs from 'node:fs';
import vm from 'node:vm';
import assert from 'node:assert/strict';
const nodes=new Map(),calls=[],mounts=[];
function node(id){if(!nodes.has(id))nodes.set(id,{innerHTML:'',value:'',textContent:'',open:false,showModal(){this.open=true},close(){this.open=false}});return nodes.get(id)}
const snapshot={available:true,system:{proxies:[{name:'HTTP',enabled:false}],vpn:{name:'Clash',state:'Connected'}},mode:'rule',revision:'mode-revision',version:'fixture',time:1,memory:10,connection_count:1,groups:[]};
const context=vm.createContext({window:{},document:{querySelectorAll:()=>[]},Date,Number,JSON,me:{role:'admin'},$:node,esc:s=>String(s??'').replaceAll('<','&lt;').replaceAll('>','&gt;'),bytes:String,panel:(title,body)=>title+body,empty:String,table:(heads,rows)=>rows.join(''),notify(){},showError:e=>{throw e},RemoteHubProxyNodes:{mount:async(data,check,options)=>mounts.push({data,check:check(),options})},withBusy:async(button,key,label,work)=>work(),api:async(path,body)=>{
 calls.push({path,body});
 if(path==='/proxy')return snapshot;
 if(path==='/proxy/manager')return {managed:false};
 if(path==='/proxy/connections')return {total:1,entries:[{host:'<bad>.invalid',port:'443',chains:['DIRECT'],upload:1,download:2}]};
 throw Error('Unexpected request '+path);
}});
vm.runInContext(fs.readFileSync('static/proxy.js','utf8'),context);
await context.window.RemoteHubProxy.render(()=>true);
assert.equal(mounts.length,1);assert.equal(mounts[0].data,snapshot);assert.equal(mounts[0].check,true);
assert.match(node('#content').innerHTML,/Clash VPN · 已连接/);
assert.match(node('#content').innerHTML,/HTTP <strong>关闭/);
assert.ok(!node('#content').innerHTML.includes('proxyGroup0'),'Old node dropdown is removed');
await node('#proxyConnections').onclick();
assert.equal(node('#workspaceDetailDialog').open,true);
assert.match(node('#workspaceDetailBody').innerHTML,/&lt;bad&gt;.invalid/);
console.log('Proxy integration: native node panel mounting, truthful system status, escaped focused connections passed.');
