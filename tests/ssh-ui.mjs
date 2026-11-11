import assert from 'node:assert/strict';
import fs from 'node:fs';
import vm from 'node:vm';

// Exercise the real dialog code with a browser-like queued close event.
class Dialog {
  open = false;
  listeners = {};
  content = '';
  controls = [];
  form = {oninput:null, onsubmit:null};
  addEventListener(name, callback) { this.listeners[name] = callback; }
  setAttribute() {}
  set innerHTML(value) { this.content = value; }
  get innerHTML() { return this.content; }
  replaceChildren() { this.content = ''; }
  querySelector(selector) {
    if (selector === 'form') return this.form;
    return {onclick:null, hidden:false, textContent:''};
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
const context = {
  window: {}, document: {createElement:() => dialog, body:{append(){}}},
  esc: value => String(value ?? ''), confirmAction:async () => true,
  FormData: class { *[Symbol.iterator]() { yield ['name','fixture']; } },
  api: () => new Promise(resolve => { resolveRequest = resolve; }),
  withBusy: async (button, key, label, work) => work(),
  setTimeout, console, URL, Object, encodeURIComponent
};
let source = fs.readFileSync('static/ssh.js', 'utf8');
source = source.replace('return {render, canLeave, reset, isDirty: () => dirty};',
  'return {render, canLeave, reset, isDirty: () => dirty, test:{open, attachForm, request, leaveDialog, setCurrent:fn=>{current=fn}}};');
vm.createContext(context);
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
console.log('SSH dialog transitions, in-flight guard, and stale-response isolation passed');
