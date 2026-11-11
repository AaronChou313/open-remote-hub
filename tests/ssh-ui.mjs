import assert from 'node:assert/strict';
import fs from 'node:fs';
import vm from 'node:vm';

// Exercise the real dialog code with a browser-like queued close event.
class Dialog {
  open = false;
  listeners = {};
  content = '';
  controls = [];
  form = {oninput:null, onsubmit:null, querySelector:() => null};
  addEventListener(name, callback) { this.listeners[name] = callback; }
  setAttribute() {}
  set innerHTML(value) { this.content = value; }
  get innerHTML() { return this.content; }
  replaceChildren() { this.content = ''; }
  querySelector(selector) {
    if (selector === 'form') return this.form;
    return {onclick:null, hidden:false, textContent:'', focus(){}, select(){}};
  }
  querySelectorAll() { return this.controls; }
  showModal() { this.open = true; }
  close() {
    this.open = false;
    queueMicrotask(() => this.listeners.close?.());
  }
}
const dialog = new Dialog();
let resolveRequest;
let copyHandler;
let copiedText;
const context = {
  window: {}, document: {createElement:() => dialog, body:{append(){}}, addEventListener(type, handler){ if(type === 'copy') copyHandler = handler; }, removeEventListener(){ copyHandler = null; }, execCommand(){ copyHandler({clipboardData:{setData(type,text){copiedText = text;}}, preventDefault(){}}); return true; }},
  esc: value => String(value ?? ''), confirmAction:async () => true,
  FormData: class { *[Symbol.iterator]() { yield ['name','fixture']; } },
  api: () => new Promise(resolve => { resolveRequest = resolve; }),
  withBusy: async (button, key, label, work) => work(),
  setTimeout, console, URL, Object, encodeURIComponent
};
let source = fs.readFileSync('static/ssh.js', 'utf8');
source = source.replace('return {render, canLeave, reset, isDirty: () => dirty};',
  'return {render, canLeave, reset, isDirty: () => dirty, test:{open, attachForm, request, leaveDialog, copyPublic, actionDialog, connectionFacts, setCurrent:fn=>{current=fn}}};');
vm.createContext(context);
vm.runInContext(fs.readFileSync('static/icons.js', 'utf8'), context);
vm.runInContext(source, context);
const ssh = context.window.RemoteHubSSH;
ssh.test.setCurrent(() => true);
await ssh.test.open('详情', 'detail');
await ssh.test.open('编辑', 'edit');
await Promise.resolve();
assert.equal(dialog.open, true);
assert.match(dialog.content, /编辑/);
assert.match(dialog.content, /edit/);

let completed = false;
ssh.test.attachForm(async () => { await ssh.test.request('/ssh/fixture', {}); completed = true; });
const submitted = dialog.form.onsubmit({preventDefault(){}, submitter:{}});
assert.equal(await ssh.canLeave(), false, 'in-flight writes retain their focused form');
ssh.reset();
ssh.test.setCurrent(() => true);
await ssh.test.open('新窗口', 'fresh');
resolveRequest({ok:true});
await submitted;
assert.equal(completed, false, 'an old response cannot complete in a new dialog');
assert.match(dialog.content, /fresh/);
assert.equal(dialog.open, true);
await ssh.test.copyPublic('ssh-ed25519 isolated-public-fixture');
assert.equal(copiedText, 'ssh-ed25519 isolated-public-fixture');
let actionCount = 0;
await ssh.test.actionDialog('删除密钥', '确认删除选中的密钥', async () => { actionCount++; });
assert.doesNotMatch(dialog.content, /管理员登录密码|current-password|name="password"/);
await dialog.form.onsubmit({preventDefault(){}, submitter:{}});
assert.equal(actionCount, 1, 'one confirmation directly completes an authorized action');
assert.doesNotMatch(source, /\/ssh\/reauth|\/ssh\/config\/trust/);
console.log('SSH dialogs, session-authorized actions, stale responses, and HTTP public-key copy passed');

assert.doesNotMatch(source, /ssh-manage-menu|keyDetails|data-ssh="details"/);
const facts = ssh.test.connectionFacts({alias:'lab',authentication:'password'},{hostname:'127.0.0.1',user:'tester',port:'2222'});
assert.match(facts,/127\.0\.0\.1/);
assert.match(facts,/tester/);
assert.match(facts,/2222/);
assert.match(facts,/密码/);
console.log('SSH cards display connection facts directly and omit management menus.');

assert.match(source,/id="sshFilterPanel" popover/);
assert.match(source,/id="sshFavorites" type="checkbox"/);
assert.doesNotMatch(source,/id="sshFavorites" aria-pressed/);
