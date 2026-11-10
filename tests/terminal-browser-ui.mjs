import fs from 'node:fs';
import vm from 'node:vm';
import assert from 'node:assert/strict';

const nodes=new Map(),documentEvents=new Map(),windowEvents=new Map(),sent=[],pasted=[];
let legacyWorks=true,legacyCalls=0,secureWrites=0;
function element(tag='div'){
 const listeners=new Map();
 return {tagName:tag.toUpperCase(),value:'',hidden:false,dataset:{},style:{},open:false,
  setAttribute(name,value){this[name]=value},getAttribute(name){return this[name]},appendChild(child){this.child=child},remove(){},
  focus(){listeners.get('focus')?.({})},blur(){listeners.get('blur')?.({})},select(){},setSelectionRange(){},
  attachShadow(){return {appendChild:child=>{this.shadowChild=child}}},
  addEventListener(name,fn){listeners.set(name,fn)},dispatch(name,event={}){return listeners.get(name)?.(event)},
  showModal(){this.open=true},close(){this.open=false},closest(selector){return this.isTerminal?this:null}
 };
}
function node(id){if(!nodes.has(id))nodes.set(id,element());return nodes.get(id)}
const native={getSelection:()=>'',options:{},paste:text=>pasted.push(text)};
class Addon{constructor(base64,provider){this.provider=provider}}
const document={currentScript:{dataset:{mobileCompatible:'true'}},readyState:'complete',activeElement:null,body:element(),getElementById:node,querySelector:()=>null,createElement:element,addEventListener:(name,fn)=>documentEvents.set(name,fn),removeEventListener:(name)=>documentEvents.delete(name),execCommand:()=>{legacyCalls++;if(legacyWorks)documentEvents.get('copy')?.({clipboardData:{setData(){}},preventDefault(){}});return legacyWorks}};
const window={term:native,isSecureContext:false,ClipboardAddon:{ClipboardAddon:Addon},matchMedia:()=>({matches:true}),addEventListener:(name,fn)=>windowEvents.set(name,fn),dispatchEvent:event=>windowEvents.get(event.type)?.(event)};
const context=vm.createContext({window,document,navigator:{platform:'Win32',userAgent:'test',maxTouchPoints:1},CustomEvent:class{constructor(type,options){this.type=type;this.detail=options.detail}},Array,Promise,Error,JSON,Number,String,Math,Set,setTimeout(){return 1},clearTimeout(){},location:{pathname:'/terminal/fixture'},AbortSignal,fetch:async()=>({ok:true,json:async()=>({path:'/private/test.png'})})});
vm.runInContext(fs.readFileSync('static/terminal-browser.js','utf8'),context);
const api=window.RemoteHubTerminal;
const addon=new window.ClipboardAddon.ClipboardAddon();
await addon.provider.writeText('c','中文 clipboard');
assert.ok(legacyCalls>0);
assert.match(node('orh-terminal-status').textContent,/已发送复制请求/);
legacyWorks=false;
await addon.provider.writeText('c','retry text');
assert.equal(node('orh-terminal-copy').hidden,false);
assert.match(node('orh-terminal-status').textContent,/浏览器阻止/);
window.isSecureContext=true;context.navigator.clipboard={writeText:async()=>{secureWrites++}};
assert.equal(await api.copy('secure'),true);assert.equal(secureWrites,1);

api.installMobileInput(native,text=>sent.push(text));
const input=window.__zjSoftKbdCapture.element;
assert.equal(input.tagName,'TEXTAREA','Mobile input supports Chinese IME');
assert.equal(window.__zjSoftKbdEnabled,undefined,'Installing mobile input never requests the keyboard');
const baseline=input.value;
input.dispatch('compositionstart');
input.value=baseline.slice(0,4)+'ni'+baseline.slice(4);
input.dispatch('input',{isComposing:true});
input.dispatch('keydown',{key:'Enter',isComposing:true,preventDefault(){throw Error('IME Enter must select its candidate')}});
assert.deepEqual(sent,[],'Uncommitted pinyin never reaches the terminal');
input.value=baseline.slice(0,4)+'你好哈哈'+baseline.slice(4);
input.dispatch('compositionend');
input.dispatch('input',{isComposing:false});
assert.deepEqual(sent,['你好哈哈'],'Committed Chinese is sent exactly once, including repeated characters');
input.dispatch('keydown',{key:'Enter',preventDefault(){}});
assert.equal(sent.at(-1),'\r');
node('orh-terminal-keyboard').onclick();
assert.equal(window.__zjSoftKbdEnabled,true);
node('orh-terminal-keyboard').onclick();
assert.equal(window.__zjSoftKbdEnabled,false);
assert.ok(!windowEvents.has('touchend')&&!windowEvents.has('click'),'No global tap-to-refocus loop');

const target=element();target.isTerminal=true;
const event={target,key:'v',ctrlKey:true,preventDefault(){this.prevented=true},stopImmediatePropagation(){this.stopped=true}};
documentEvents.get('keydown')(event);
assert.equal(event.stopped,true);assert.ok(!event.prevented,'Browser must dispatch its real paste event');
const paste={target,clipboardData:{items:[],getData:()=> 'first\nsecond'},preventDefault(){this.prevented=true},stopImmediatePropagation(){}};
documentEvents.get('paste')(paste);
assert.equal(pasted.at(-1),'first\nsecond','Text uses the native terminal paste path');
const cancel={...event,key:'c',stopped:false,prevented:false};
documentEvents.get('keydown')(cancel);assert.equal(cancel.stopped,false,'Ctrl+C continues to interrupt the program');
await api.uploadImage({type:'image/png',size:10});
assert.equal(pasted.at(-1)," '/private/test.png' ");
assert.ok(!pasted.at(-1).includes('\r')&&!pasted.at(-1).includes('\n'),'Image path never submits a command');
console.log('Terminal browser: HTTP copy fallback, failure feedback, native paste, mobile IME and explicit keyboard focus passed.');
