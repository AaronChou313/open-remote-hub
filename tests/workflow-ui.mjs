// Interaction tests: exercise the actual handlers without touching host services.
import fs from 'node:fs';
import vm from 'node:vm';
import assert from 'node:assert/strict';
const nodes=new Map(),opened=[];
function node(selector){if(!nodes.has(selector))nodes.set(selector,{textContent:'',value:'',hidden:false,disabled:false,isConnected:true,open:false,innerHTML:'',dataset:{},classList:{add(v){this[v]=true},toggle(v,force){this[v]=force===undefined?!this[v]:force},contains(v){return!!this[v]}},setAttribute(){},removeAttribute(){},replaceChildren(){},append(){},addEventListener(){},focus(){},reset(){},close(){this.open=false},showModal(){this.open=true},closest(){return null},querySelectorAll(){return []}});return nodes.get(selector)}
const context=vm.createContext({console,AbortSignal,URL,JSON,Date,Number,Set,Map,Promise,queueMicrotask,setTimeout(){},setInterval(){},localStorage:{getItem(){return null},setItem(){}},matchMedia(){return {matches:false}},window:{open(url){opened.push(url);return {opener:{}}}},document:{body:node('body'),hidden:false,querySelector:node,querySelectorAll(){return []},createElement(){return node('new-link')},createTextNode(t){return t},addEventListener(){}},fetch(){throw Error('Unexpected network call')},EventSource:class{close(){}},prompt(){return 'renamed'}});
vm.runInContext(fs.readFileSync('static/icons.js','utf8'),context);
vm.runInContext(fs.readFileSync('static/sessions.js','utf8'),context);context.RemoteHubSessions=context.window.RemoteHubSessions;
vm.runInContext(fs.readFileSync('static/app.js','utf8').replace(/\nenter\(\);\s*$/,''),context);
vm.runInContext(`me={role:'admin',host:{system:'Darwin'}};globalThis.calls=[];globalThis.confirmations=[];globalThis.updates=0;api=async(p,b)=>{calls.push({p,b});return {id:'saved-task'}};confirmAction=async(t,m)=>{confirmations.push({t,m});return true};refresh=async()=>{updates++}`,context);
const run=code=>vm.runInContext(code,context);
node('#theme').onclick();assert.equal(node('#themeMoon').hidden,true);assert.equal(node('#themeSun').hidden,false);
node('#theme').onclick();assert.equal(node('#themeMoon').hidden,false);assert.equal(node('#themeSun').hidden,true);
await run("act('docker','container-id','start')");
assert.equal(run('confirmations.length'),0,'Starting a stopped container needs no redundant confirmation');
assert.equal(run('calls.length'),1);
await run("act('docker','container-id','stop')");
assert.equal(run('confirmations.length'),1,'Stopping has exactly one confirmation');
assert.equal(run('calls.at(-1).b.confirm'),'container-id','Backend target protection retained');
run("mountTerminal('saved-session')");
assert.equal(opened.at(-1),'/terminal/open/saved-session');
assert.ok(!opened.includes('about:blank'));
assert.equal(run('confirmations.length'),1,'Terminal entry never opens a parent-console confirmation');
run(`api=async()=>({sessions:[{name:'old',status:'exited',detail:''},{name:'live',status:'running',detail:''}],processes:[]});renderVersion=1`);
await run('zellijView(1)');
assert.match(node('#content').innerHTML,/session-grid/);
assert.ok(!node('#content').innerHTML.includes('class="notice"'),'No explanatory notice boxes');
assert.match(node('#content').innerHTML,/恢复并进入/);
assert.match(node('#content').innerHTML,/\/terminal\/open\/old/);
run(`api=async(p,b)=>{calls.push({p,b});return {id:'saved-task'}}`);
const navigation=fs.readFileSync('static/index.html','utf8');
assert.match(navigation,/data-view="applications"/);
assert.match(navigation,/data-view="services"/);
assert.doesNotMatch(navigation,/id="taskDialog"|id="taskForm"|任务与服务|快捷任务/);
assert.match(fs.readFileSync('static/workspace.js','utf8'),/switchView\('services'\)/,'Project task output opens local services');
run(`globalThis.release=null;globalThis.count=0;globalThis.work=()=>new Promise(r=>{count++;release=r});globalThis.pending=withBusy(null,'single','等待',work)`);
await run("withBusy(null,'single','等待',work)");
assert.equal(run('count'),1,'Double clicks cannot submit a second operation');
run('release()');await run('pending');
assert.equal(run('pendingOperations.size'),0,'Busy state always released');
node('#iconBusy').innerHTML=run("icon('start')")+'启动';
await run("withBusy(document.querySelector('#iconBusy'),'icon:busy','启动中…',async()=>{})");
assert.match(node('#iconBusy').innerHTML,/icons.svg#play/,'Busy state restores SVG markup');
console.log('Workflow UI: start, destructive confirmation, direct terminal entry, saved-session links, local-services navigation, duplicate protection passed.');

node('#newPassword').value='1';node('#newPasswordConfirm').value='1';
await node('#passwordForm').onsubmit({preventDefault(){}});
assert.equal(run('calls.at(-1).p'),'/auth/password');
assert.deepEqual(JSON.parse(run('JSON.stringify(calls.at(-1).b)')),{password:'1'});
const passwordMarkup=fs.readFileSync('static/index.html','utf8');
for(const id of ['password','passwordConfirm','newPassword','newPasswordConfirm']){
  const input=passwordMarkup.match(new RegExp('<input[^>]*id="'+id+'"[^>]*>'))?.[0];
  assert.ok(input);
  assert.doesNotMatch(input,/minlength|maxlength|required/,'password input has no length constraint');
}
assert.doesNotMatch(passwordMarkup,/id="currentPassword"/);
console.log('Password form uses current admin session and accepts unrestricted passwords.');

node('#sidebarToggle').onclick();
assert.equal(node('body').classList.contains('sidebar-collapsed'),true);
node('#sidebarToggle').onclick();
assert.equal(node('body').classList.contains('sidebar-collapsed'),false);
assert.doesNotMatch(passwordMarkup,/id="subtitle"|个人基础设施/);
console.log('Compact page headings and icon-only sidebar toggle passed.');
