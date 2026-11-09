import fs from 'node:fs';
import vm from 'node:vm';
import assert from 'node:assert/strict';

const nodes=new Map(),requests=[];
let responses=[],refreshes=0;
function node(selector){
 if(!nodes.has(selector))nodes.set(selector,{textContent:'',innerHTML:'',value:0,hidden:false,open:false,disabled:false,replaceChildren(){this.innerHTML=''},showModal(){this.open=true},close(){this.open=false}});
 return nodes.get(selector);
}
class XHR{
 constructor(){this.upload={};this.status=0;this.responseText=''}
 open(method,url){this.method=method;this.url=url}
 setRequestHeader(name,value){this.header=[name,value]}
 send(file){
  requests.push({url:this.url,file,header:this.header});
  const response=responses.shift();assert.ok(response,'Unexpected upload request');
  if(response.defer)return;
  queueMicrotask(()=>{
   this.upload.onprogress({loaded:file.size});
   this.status=response.status;
   this.responseText=JSON.stringify({detail:'existing file'});
   this.onload();
  });
 }
 abort(){this.onabort()}
}
const context=vm.createContext({window:{},URLSearchParams,XMLHttpRequest:XHR,Promise,Array,Math,JSON,Object,Error,$:node,bytes:n=>String(n),esc:s=>String(s).replaceAll('<','&lt;'),showError:error=>{throw error},showLogin(){throw Error('Unexpected login redirect')}});
vm.runInContext(fs.readFileSync('static/uploads.js','utf8'),context);
const uploads=context.window.RemoteHubUploads;
const files=[{name:'a.py',webkitRelativePath:'algorithm/src/a.py',size:3},{name:'b.py',webkitRelativePath:'algorithm/src/b.py',size:4}];
const settings={files,root:'root',path:'workspace/src',folder:true,onRefresh:async()=>{refreshes++}};
responses=[{status:200},{status:409}];
await uploads.start(settings);
assert.equal(uploads.isUploading(),false);
assert.match(node('#uploadSummary').textContent,/1 \/ 2/);
assert.equal(node('#uploadRetry').hidden,false);
assert.match(node('#uploadFailures').innerHTML,/algorithm\/src\/b.py/);
assert.equal(new URL('http://localhost'+requests[0].url).searchParams.get('path'),'workspace/src/algorithm/src/a.py');
assert.equal(new URL('http://localhost'+requests[0].url).searchParams.get('create_parents'),'true');
assert.deepEqual(requests[0].header,['X-ORH-Request','1']);
responses=[{status:200}];
await node('#uploadRetry').onclick();
assert.equal(requests.length,3,'Retry excludes already uploaded files');
assert.equal(requests[2].file.name,'b.py');
assert.equal(node('#uploadRetry').hidden,true);
assert.match(node('#uploadSummary').textContent,/2 \/ 2/);
assert.equal(refreshes,2);

responses=[{defer:true}];
const cancelled=uploads.start(settings);
assert.equal(uploads.isUploading(),true);
node('#workspaceDetailClose').onclick();
await cancelled;
assert.equal(uploads.isUploading(),false);
assert.match(node('#uploadSummary').textContent,/0 \/ 2/);
responses=[{status:200},{status:200}];
await node('#uploadRetry').onclick();
assert.match(node('#uploadSummary').textContent,/2 \/ 2/);

responses=[{defer:true}];
const loggedOut=uploads.start(settings);
uploads.reset();
node('#workspaceDetailBody').innerHTML='CLEARED';
await loggedOut;
assert.equal(node('#workspaceDetailBody').innerHTML,'CLEARED','Logout never repopulates private upload details');
assert.equal(uploads.isUploading(),false);
console.log('Uploads UI: folder paths, conflict collection, retry, cancellation and logout passed.');
