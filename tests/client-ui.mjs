import assert from 'node:assert/strict';
import fs from 'node:fs';
import vm from 'node:vm';

const nodes = new Map();
function node(selector) {
  if (!nodes.has(selector)) nodes.set(selector, {
    hidden:true, disabled:false, value:'', textContent:'', innerHTML:'', dataset:{},
    classList:{add() {}}, setAttribute() {}, focus() {},
  });
  return nodes.get(selector);
}
const navigation = [];
const calls = [];
const account = {device_id:'local', host:{hostname:'Mac'}, cloud:{bound:true, username:'aaron', cloud_url:'https://cloud.example'}};
let directory = {
  cloud:{bound:true, error:''}, mesh:{state:'Running', error:''},
  devices:[{device_id:'remote', name:'<Lab>', os:'Windows', local:false, heartbeat_online:true, path:'idle', mesh_ips:['100.64.0.9'], agent_published:true, desktop_published:false}],
};
let connect;
let failAgent = true;
const context = vm.createContext({
  console, URL, URLSearchParams, AbortSignal, setInterval() {},
  location:{origin:'http://127.0.0.1:8765', href:'http://127.0.0.1:8765/client', assign:value => navigation.push(value)},
  matchMedia:() => ({matches:false}), localStorage:{getItem:() => null},
  sessionStorage:{removeItem() {}, setItem() {}},
  document:{hidden:false, body:node('body'), querySelector:node, querySelectorAll:() => []},
  fetch:async (url, options) => {
    calls.push([url, options]);
    let value;
    if (url === '/api/me') {
      if (failAgent) throw TypeError('Failed to fetch');
      value = account;
    }
    else if (url === '/api/client/devices') value = directory;
    else if (url === '/api/client/connect') return new Promise(resolve => { connect = resolve; });
    else throw Error('Unexpected request ' + url);
    return {ok:true, status:200, json:async () => value};
  },
});
const run = source => vm.runInContext(source, context);
run(fs.readFileSync('static/client.js', 'utf8').replace(/refreshDevices\(\);\s*$/, ''));
await run('refreshDevices()');
assert.equal(node('#clientShell').hidden, false);
assert.match(node('#clientError').textContent, /Agent 无法访问/);
failAgent = false;
await run('refreshDevices()');
assert.equal(node('#clientShell').hidden, false);
assert.match(node('#clientDevices').innerHTML, /&lt;Lab&gt;/);
assert.match(node('#clientDevices').innerHTML, /Cloud 心跳在线.*链路尚未建立/);
assert.equal(node('#clientMeshSettings').href.includes('device_id=local'), true);
directory.cloud.error = 'Cloud 不可达';
await run('refreshDevices()');
assert.equal(node('#clientNotice').textContent, 'Cloud 不可达');
const button = {...node('button'), dataset:{connect:'remote'}, textContent:'进入工作区'};
const event = {target:{closest:() => button}};
const first = node('#clientDevices').onclick(event);
await node('#clientDevices').onclick(event);
assert.equal(calls.filter(([path]) => path === '/api/client/connect').length, 1);
connect({ok:true, status:200, json:async () => ({device_id:'remote', url:'http://orh-remote.localhost:12345/auth/cloud#ticket=test'})});
await first;
assert.equal(navigation.length, 1);
assert.equal(run('currentDeviceId'), 'remote');
assert.deepEqual(JSON.parse(calls.at(-1)[1].body), {device_id:'remote'});

const events = new Map();
const bar = [];
let leave = false;
let failLink = false;
const workspace = vm.createContext({
  console, URL, URLSearchParams, performance, setInterval() {},
  location:{origin:'http://orh-remote.localhost:12345', search:'?client=http%3A%2F%2F127.0.0.1%3A8765%2Fclient&device_id=remote&peer_ip=100.64.0.17', assign:value => navigation.push(value)},
  window:{addEventListener:(name, handler) => events.set(name, handler), pywebview:{state:{}}, RemoteHubWorkspace:{canLeave:async () => leave}},
  document:{hidden:false, body:{classList:{add() {}}, prepend:value => bar.push(value)}, createElement:() => ({append(...children) {this.children = children;}, setAttribute() {}}), addEventListener() {}, querySelector:node},
  api:async () => {if (failLink) throw Error('连接中断'); return {state:'Running', path:'relay'};},
  showError:error => {throw error;},
});
vm.runInContext(fs.readFileSync('static/client-workspace.js', 'utf8'), workspace);
events.get('orh:authenticated')({detail:{device_id:'remote', host:{hostname:'Lab', system:'Windows'}}});
await new Promise(resolve => setImmediate(resolve));
const status = bar[0].children[2];
assert.match(status.textContent, /Agent 已连接.*DERP 中继/);
assert.equal(workspace.window.ORHClientWorkspace.openTerminal('/terminal/open/demo'), true);
assert.equal(workspace.window.pywebview.state.terminal_request.url, 'http://orh-remote.localhost:12345/terminal/open/demo');
await workspace.window.ORHClientWorkspace.returnToDevices();
assert.equal(navigation.length, 1, 'Canceling an unsaved edit keeps the workspace');
leave = true;
await workspace.window.ORHClientWorkspace.returnToDevices();
assert.equal(navigation.at(-1), 'http://127.0.0.1:8765/client');
failLink = true;
events.get('orh:authenticated')({detail:{device_id:'remote', host:{hostname:'Lab', system:'Windows'}}});
await new Promise(resolve => setImmediate(resolve));
assert.match(status.textContent, /Agent API 不可达/);
events.get('orh:login-required')();
assert.match(status.textContent, /登录已失效/);
events.get('orh:authenticated')({detail:{device_id:'different-device', host:{}}});
assert.match(status.textContent, /身份不匹配/);
assert.equal(node('#shell').hidden, true);
console.log('Client UI passed device selection, Cloud errors, path status, native terminal routing and unsaved-edit navigation.');

for (const [search, expected] of [['?android_client=1&device_id=remote', '/?android_client=1&device_id=remote#overview'], ['?client_entry=1', '/client']]) {
  let redirected;
  const loginLocation = {hash:'#ticket=single-use', search, pathname:'/auth/cloud', replace:value => {redirected=value;}};
  await vm.runInNewContext(fs.readFileSync('static/cloud-auth.js','utf8'), {
    URLSearchParams, location:loginLocation,
    history:{replaceState(_state,_title,address) {loginLocation.search=new URL(address,'http://local').search;}},
    fetch:async () => ({ok:true,json:async () => ({})}),
    document:{querySelector:node},
  });
  assert.equal(redirected, expected);
}
