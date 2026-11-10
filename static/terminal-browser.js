'use strict';
// Keep input in Zellij's native terminal. This layer handles browser clipboard
// transfers and supplies an IME-capable mobile capture to the native client.
window.RemoteHubTerminal=(()=>{
 let copiedText='',noticeTimer=null,uploading=false;
 const mobileCompatible=document.currentScript?.dataset.mobileCompatible==='true';
 const terminal=()=>window.term;
 const coarse=()=>window.matchMedia('(pointer: coarse)').matches||navigator.maxTouchPoints>0||/Mobi|Android|iPhone|iPad/i.test(navigator.userAgent);
 const mac=()=>/Mac|iPhone|iPad/i.test(navigator.platform||navigator.userAgent);
 const node=id=>document.getElementById(id);
 function notify(message,failed=false){
  const status=node('orh-terminal-status');if(!status)return;
  status.textContent=message;status.hidden=false;
  status.dataset.failed=String(failed);
  clearTimeout(noticeTimer);
  noticeTimer=setTimeout(()=>{status.hidden=true},failed?10000:2200);
 }
 function legacyCopy(text){
  const active=document.activeElement;
  const input=document.createElement('textarea');input.value=text;
  input.setAttribute('aria-label','复制内容');input.className='orh-copy-buffer';
  const dialog=document.querySelector('dialog[open]');
  (dialog||document.body).appendChild(input);
  input.focus();input.select();input.setSelectionRange(0,text.length);
  let ok=false,wrote=false;
  const write=event=>{
   if(!event.clipboardData)return;
   event.clipboardData.setData('text/plain',text);event.preventDefault();wrote=true;
  };
  document.addEventListener('copy',write,true);
  try{ok=document.execCommand('copy')&&wrote}catch{}
  finally{document.removeEventListener('copy',write,true)}
  input.remove();
  active?.focus({preventScroll:true});
  return ok;
 }
 async function copy(text){
  if(!text){notify('请先选中终端文字');return false}
  copiedText=text;
  try{
   if(window.isSecureContext&&navigator.clipboard?.writeText){
    await navigator.clipboard.writeText(text);notify('已复制到当前设备');return true;
   }
   if(!legacyCopy(text))throw Error('Clipboard unavailable');
   notify('已发送复制请求；未生效时点“复制”');
   if(node('orh-terminal-copy'))node('orh-terminal-copy').hidden=false;
   return true;
  }catch{
   if(legacyCopy(text)){
    notify('已发送复制请求；未生效时点“复制”');
    if(node('orh-terminal-copy'))node('orh-terminal-copy').hidden=false;
    return true;
   }
   notify('自动复制被浏览器阻止，点“复制”再试',true);
   if(node('orh-terminal-copy'))node('orh-terminal-copy').hidden=false;
   return false;
  }
 }
 function installClipboard(){
  const Native=window.ClipboardAddon?.ClipboardAddon;
  if(!Native)return;
  const provider={
   readText:async selection=>selection==='c'&&navigator.clipboard?.readText?await navigator.clipboard.readText():'',
   writeText:async(selection,text)=>{if(selection==='c')await copy(text)}
  };
  window.ClipboardAddon.ClipboardAddon=class extends Native{
   constructor(base64,custom){super(base64,custom||provider)}
  };
 }
 function inputDiff(before,after){
  const a=Array.from(before),b=Array.from(after);
  let prefix=0,suffix=0;
  while(prefix<Math.min(a.length,b.length)&&a[prefix]===b[prefix])prefix++;
  while(suffix<Math.min(a.length,b.length)-prefix&&a[a.length-1-suffix]===b[b.length-1-suffix])suffix++;
  return {deleted:a.length-prefix-suffix,inserted:b.slice(prefix,b.length-suffix).join('').replaceAll('\u00a0','')};
 }
 function installMobileInput(term,sendFunction){
  if(!coarse())return;
  if(window.__zjSoftKbdCapture?.installed){window.__zjSoftKbdCapture.sendFn=sendFunction;return}
  const state={installed:true,sendFn:sendFunction,isFocused:false,element:null};
  window.__zjSoftKbdCapture=state;
  const host=document.createElement('div');host.id='zj-mobile-capture-host';
  host.className='orh-mobile-input';host.setAttribute('aria-hidden','true');document.body.appendChild(host);
  const input=document.createElement('textarea');input.id='zj-mobile-capture';
  input.setAttribute('autocomplete','off');input.setAttribute('autocorrect','off');
  input.setAttribute('autocapitalize','off');input.setAttribute('inputmode','text');
  input.setAttribute('spellcheck','false');input.setAttribute('aria-label','终端输入');input.tabIndex=-1;
  host.attachShadow({mode:'closed'}).appendChild(input);
  // iOS needs a focusable, font-size >=16px control to show its full IME.
  input.style.cssText='position:fixed;top:0;left:0;width:1px;height:1px;font-size:16px;opacity:0;border:0;padding:0;';
  state.element=input;
  const syncCursor=()=>{term.options.cursorInactiveStyle=term.options.cursorStyle||'block'};
  syncCursor();window.__zjSyncInactiveCursorStyle=syncCursor;
  let composing=false,last='';
  const reset=()=>{last='\u00a0'.repeat(8);input.value=last;input.setSelectionRange(4,4)};
  const update=event=>{
   if(composing||event?.isComposing)return;
   const value=input.value;
   if(value===last)return;
   const change=inputDiff(last,value);
   if(change.deleted)state.sendFn('\x7f'.repeat(change.deleted));
   if(change.inserted)state.sendFn(change.inserted);
   last=value;
   if(event?.inputType==='deleteContentBackward'||value.length>4096)reset();
  };
  reset();
  input.addEventListener('compositionstart',()=>{composing=true});
  input.addEventListener('compositionend',()=>{composing=false;update()});
  input.addEventListener('input',update);
  input.addEventListener('keydown',event=>{
   if(composing||event.isComposing||event.keyCode===229)return;
   const controls={Enter:'\r',Tab:'\t',Escape:'\x1b',ArrowUp:'\x1b[A',ArrowDown:'\x1b[B',ArrowRight:'\x1b[C',ArrowLeft:'\x1b[D'};
   if(controls[event.key]){event.preventDefault();state.sendFn(controls[event.key]);if(event.key==='Enter')reset()}
  });
  input.addEventListener('focus',()=>{
   state.isFocused=true;
   window.dispatchEvent(new CustomEvent('zellij:soft-keyboard-visibility',{detail:{visible:true}}));
  });
  input.addEventListener('blur',()=>{
   state.isFocused=false;window.__zjSoftKbdEnabled=false;
   window.dispatchEvent(new CustomEvent('zellij:soft-keyboard-visibility',{detail:{visible:false}}));
  });
  // No touch/click refocus loop. The native keyboard button and explicit taps
  // while keyboard mode is enabled own focus and the native gestures own scroll.
 }
 function terminalEvent(event){
  return !!terminal()&&!node('orh-terminal-help')?.open&&(
   event.target?.closest?.('#terminal,#zj-mobile-capture-host')||
   event.target===window.__zjSoftKbdCapture?.element
  );
 }
 async function uploadImage(file){
  if(uploading){notify('图片正在上传');return}
  if(!file||!['image/png','image/jpeg','image/webp'].includes(file.type)){notify('请选择 PNG、JPEG 或 WebP 图片',true);return}
  if(file.size>20*1024**2){notify('图片上限为 20 MiB',true);return}
  const term=terminal();if(!term){notify('请等待终端连接',true);return}
  uploading=true;notify('正在上传图片…');
  try{
   const name=decodeURIComponent(location.pathname.split('/').pop());
   const response=await fetch('/api/terminal/'+encodeURIComponent(name)+'/attachments',{
    method:'POST',headers:{'X-ORH-Request':'1','Content-Type':file.type},body:file,signal:AbortSignal.timeout(120000)
   });
   const result=await response.json();
   if(!response.ok)throw Error(typeof result.detail==='string'?result.detail:'图片上传失败');
   const path=" '"+result.path.replaceAll("'","'\\''")+"' ";
   term.paste(path);
   notify('图片已上传，路径已插入终端');
  }catch(error){notify(error.message||'图片上传失败，请重试',true)}
  finally{uploading=false}
 }
 function mount(){
  const controls=document.createElement('div');controls.className='orh-terminal-tools zj-mobile-chrome';
  controls.innerHTML='<button id="orh-terminal-copy" type="button" hidden>复制</button><button id="orh-terminal-keyboard" type="button" aria-pressed="false" hidden>键盘</button><button id="orh-terminal-help-open" type="button" aria-label="剪贴板与快捷键">剪贴板</button><input id="orh-terminal-image" type="file" accept="image/png,image/jpeg,image/webp" hidden>';
  document.body.appendChild(controls);
  const status=document.createElement('div');status.id='orh-terminal-status';status.className='zj-mobile-chrome';status.setAttribute('role','status');status.hidden=true;document.body.appendChild(status);
  const help=document.createElement('dialog');help.id='orh-terminal-help';help.className='zj-mobile-chrome';help.setAttribute('aria-labelledby','orh-terminal-help-title');
  help.innerHTML='<div class="orh-terminal-help-head"><h2 id="orh-terminal-help-title">剪贴板与快捷键</h2><button id="orh-terminal-help-close" type="button">关闭</button></div><p>选中文字会尝试自动复制。无法粘贴时，点击“复制”使用浏览器原生复制。按住 Shift 拖选可使用浏览器终端的选区。</p><table><thead><tr><th>操作</th><th>Windows / Linux</th><th>Mac</th></tr></thead><tbody><tr><td>复制选区</td><td>Ctrl + Shift + C</td><td>⌘ C</td></tr><tr><td>粘贴文字</td><td>Ctrl + V / Ctrl + Shift + V</td><td>⌘ V</td></tr><tr><td>粘贴图片</td><td>Ctrl + V</td><td>⌘ V</td></tr><tr><td>中断程序</td><td>Ctrl + C</td><td>Ctrl + C</td></tr><tr><td>锁定 / 解锁 Zellij</td><td>Ctrl + G</td><td>Ctrl + G</td></tr></tbody></table><p>手机默认查看输出，可上下滑动。点击右上角“键盘”开始输入，再次点击收起键盘。中文在终端内组合输入。</p><p>图片会上传到 Mac，并将文件路径插入当前终端。Codex 可识别图片路径；程序在容器内时，需使用容器可访问的文件路径。</p><div class="orh-terminal-help-actions"><button id="orh-terminal-copy-current" type="button">复制选中内容</button><button id="orh-terminal-upload" type="button">上传图片</button></div><label for="orh-terminal-copy-text">最近选择的文字</label><textarea id="orh-terminal-copy-text" readonly placeholder="尚未选中文字，可在终端选中后返回这里复制。"></textarea><p id="orh-terminal-copy-hint" hidden></p><p id="orh-terminal-compat-warning" hidden>当前 Zellij 版本尚未匹配移动端适配，手机输入行为请以实际版本为准。</p>';
  document.body.appendChild(help);
  const openHelp=()=>{
   node('orh-terminal-copy-text').value=terminal()?.getSelection()||copiedText;
   node('orh-terminal-compat-warning').hidden=mobileCompatible;
   help.showModal();
  };
  const manualCopy=()=>{
   if(!help.open)openHelp();
   const text=node('orh-terminal-copy-text');text.value=terminal()?.getSelection()||copiedText;
   text.focus();text.select();text.setSelectionRange(0,text.value.length);
   const hint=mac()?'按 ⌘ C 复制，手机可长按文字选择“复制”':'按 Ctrl+C 复制选中的文字';
   node('orh-terminal-copy-hint').textContent=hint;node('orh-terminal-copy-hint').hidden=false;
  };
  node('orh-terminal-help-open').onclick=openHelp;
  node('orh-terminal-help-close').onclick=()=>help.close();
  const keyboard=node('orh-terminal-keyboard');keyboard.hidden=!coarse()||!mobileCompatible;
  keyboard.onclick=()=>{
   const capture=window.__zjSoftKbdCapture;
   if(!capture?.element){notify('请等待终端连接');return}
   const enabled=!window.__zjSoftKbdEnabled;
   window.__zjSoftKbdEnabled=enabled;
   if(enabled)capture.element.focus({preventScroll:true});else capture.element.blur();
   keyboard.setAttribute('aria-pressed',String(enabled));
  };
  window.addEventListener('zellij:soft-keyboard-visibility',event=>keyboard.setAttribute('aria-pressed',String(event.detail.visible)));
  const copyFromControl=()=>window.isSecureContext?copy(terminal()?.getSelection()||copiedText):manualCopy();
  node('orh-terminal-copy').onclick=copyFromControl;
  node('orh-terminal-copy-current').onclick=copyFromControl;
  node('orh-terminal-upload').onclick=()=>{help.close();node('orh-terminal-image').click()};
  node('orh-terminal-image').onchange=event=>{const file=event.target.files[0];event.target.value='';uploadImage(file)};
  document.addEventListener('keydown',event=>{
   if(!terminalEvent(event)||event.isComposing)return;
   const key=event.key.toLowerCase();
   if(key==='c'&&((event.ctrlKey&&event.shiftKey&&!event.altKey)||(event.metaKey&&mac()))){
    const selected=terminal().getSelection();
    if(selected){event.preventDefault();event.stopImmediatePropagation();copy(selected)}
   }
   // Let the browser emit a paste event instead of sending Ctrl+V to the host
   // application, which would read the server's unrelated system clipboard.
   if(key==='v'&&event.ctrlKey&&!mac()&&!event.altKey&&!event.metaKey){event.stopImmediatePropagation()}
  },true);
  document.addEventListener('paste',event=>{
   if(!terminalEvent(event))return;
   const images=Array.from(event.clipboardData?.items||[]).filter(item=>item.kind==='file'&&item.type.startsWith('image/'));
   if(images.length){event.preventDefault();event.stopImmediatePropagation();uploadImage(images[0].getAsFile());return}
   const text=event.clipboardData?.getData('text/plain');
   if(text){event.preventDefault();event.stopImmediatePropagation();terminal().paste(text)}
  },true);
  document.addEventListener('mouseup',event=>{
   if(!terminalEvent(event))return;
   const text=terminal().getSelection();if(text)copy(text);
  });
 }
 installClipboard();
 if(document.readyState==='loading')document.addEventListener('DOMContentLoaded',mount,{once:true});else mount();
 return {installMobileInput,inputDiff,copy,uploadImage};
})();
