import assert from 'node:assert/strict';
import fs from 'node:fs';
import vm from 'node:vm';

const nodes = new Map();
const node = selector => {
  if (selector === '#kbNoteBody') return null;
  if (!nodes.has(selector)) nodes.set(selector, {disabled:false, textContent:'', isConnected:true});
  return nodes.get(selector);
};
let resolveSave;
let confirmed = false;
let wrote;
const context = {
  window:{addEventListener(){}}, document:{addEventListener(){}},
  $:node, me:{role:'admin'}, icon:name=>`<svg>${name}</svg>`,
  esc:value=>String(value ?? '').replace(/[&<>"']/g, character=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[character])),
  confirmAction:async()=>confirmed, notify(){}, showError(){}, console,
  withBusy:async(control,key,label,work)=>work(),
  api:async(path,body)=>{wrote={path,body};return new Promise(resolve=>{resolveSave=resolve;});},
  URLSearchParams, encodeURIComponent, Set, Map, Object, Date
};
vm.createContext(context);
vm.runInContext(fs.readFileSync('static/vendor/marked.js','utf8'),context);
assert.match(context.marked.parse('# Markdown\n\n**中文**\n\n- [x] task'),/<h1>Markdown<\/h1>/);
let source = fs.readFileSync('static/knowledge.js','utf8');
source = source.replace('return {render, canLeave, reset, isDirty:() => dirty};',
  `return {render, canLeave, reset, isDirty:()=>dirty, test:{treeMarkup, relativePath, save,
    setup(value){library={id:'fixture'};note={path:'folder/note.md',text:'old',revision:'before'};draft=value;dirty=true;current=()=>true;},
    draft(value){draft=value;dirty=draft!==note.text;}, revision:()=>note.revision}};`);
vm.runInContext(source,context);
const knowledge = context.window.RemoteHubKnowledge;
assert.equal(knowledge.test.relativePath('../image.png','folder/note.md'),'image.png');
assert.equal(knowledge.test.relativePath('../../escape.md','folder/note.md'),null);
assert.equal(knowledge.test.relativePath('https://example.org/file.md','note.md'),null);
const tree = knowledge.test.treeMarkup([
  {path:'研究',name:'研究',kind:'directory'},
  {path:'研究/定位.md',name:'定位.md',kind:'file'},
  {path:'unrelated.md',name:'unrelated.md',kind:'file'},
  {path:'<script>.md',name:'<script>.md',kind:'file'},
], '定位');
assert.match(tree,/研究/);
assert.match(tree,/定位/);
assert.doesNotMatch(tree,/unrelated|<script>/);
knowledge.test.setup('submitted');
assert.equal(await knowledge.canLeave(),false);
assert.equal(knowledge.isDirty(),true);
const saving = knowledge.test.save();
await Promise.resolve();
knowledge.test.draft('typed while saving');
resolveSave({revision:'after',modified:0});
await saving;
assert.equal(wrote.body.text,'submitted');
assert.equal(knowledge.test.revision(),'after');
assert.equal(knowledge.isDirty(),true,'new edits remain unsaved after an earlier save completes');
assert.equal(node('#kbSave').disabled,false);
confirmed = true;
assert.equal(await knowledge.canLeave(),true);
knowledge.reset();
assert.equal(knowledge.isDirty(),false);
console.log('Knowledge Markdown, tree filtering, paths, save races, and unsaved-edit guards passed');
