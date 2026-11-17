import fs from 'node:fs';
import vm from 'node:vm';
import assert from 'node:assert/strict';
const body={dataset:{module:'modules'}};
let content='';
const buttons=[{dataset:{module:'files',operation:'disable'}}];
const root={get innerHTML(){return content},set innerHTML(value){content=value},querySelectorAll(selector){return selector==='button[data-module]'?buttons:[]}};
const context=vm.createContext({window:{},caps:{},esc:String,api:async()=>({modules:[{id:'files',group:'basic',entry:'files',name:'文件管理',state:'ready',supported:true,enabled:true,dependency:{detail:'内置'},guide:{}},{id:'docker',group:'advanced',entry:'docker',name:'Docker',state:'missing_dependency',supported:true,enabled:true,dependency:{detail:'Docker 已安装，Engine 尚未启动',installed:true,can_open:true},guide:{text:'安装 Docker',url:'https://example.invalid'}}]}),
 document:{body,querySelector:()=>({}),querySelectorAll:selector=>selector==='[data-module]'?[body,...buttons]:[]},$:()=>root});
vm.runInContext(fs.readFileSync('static/modules.js','utf8'),context);
await context.window.RemoteHubModules.render(()=>true);
assert.equal(body.onclick,undefined,'Module management must never attach an operation handler to body');
assert.equal(typeof buttons[0].onclick,'function');
assert.match(content,/后台未就绪/);assert.match(content,/打开 Docker Desktop/);assert.doesNotMatch(content,/安装说明/);
assert.match(content,/基本功能/);assert.match(content,/进阶功能/);
const sprite=fs.readFileSync('static/icons.svg','utf8');
assert.match(sprite,/<symbol id="monitor"[^>]*fill="none"[^>]*stroke="currentColor"/);
console.log('Module operations stay scoped to their own buttons, groups and outlined monitor icon render correctly.');
