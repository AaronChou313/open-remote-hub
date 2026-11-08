'use strict';
if(localStorage.getItem('orh-theme')==='dark'||(!localStorage.getItem('orh-theme')&&matchMedia('(prefers-color-scheme: dark)').matches))document.body.classList.add('dark');
const sessionName=decodeURIComponent(location.pathname.split('/').pop());
let preparing=false,waitingForLogin=false;
document.querySelector('#entryName').textContent=sessionName;
document.title='进入 '+sessionName+' · OpenRemoteHub';
async function prepare(){
 if(preparing)return;preparing=true;
 const status=document.querySelector('#entryStatus'),retry=document.querySelector('#entryRetry'),login=document.querySelector('#entryLogin');
 retry.hidden=true;login.hidden=true;status.textContent='正在准备会话，完成后自动进入…';status.setAttribute('aria-busy','true');
 try{
  const r=await fetch('/api/zellij/'+encodeURIComponent(sessionName)+'/enter',{method:'POST',headers:{'Content-Type':'application/json','X-ORH-Request':'1'},body:'{}',signal:AbortSignal.timeout(45000)});
  const d=await r.json();
  if(!r.ok){waitingForLogin=r.status===401||r.status===403;login.hidden=!waitingForLogin;throw Error(waitingForLogin?'登录已过期。点击登录，完成后返回此页即可自动继续。':typeof d.detail==='string'?d.detail:'暂时无法进入终端')}
  waitingForLogin=false;status.textContent='会话已就绪，正在进入…';location.replace(d.url);
 }catch(e){status.textContent=e.name==='TimeoutError'?'准备时间较长，请重试。已创建的会话会直接复用，不会重复启动。':e.message;retry.hidden=false}
 finally{preparing=false;status.removeAttribute('aria-busy')}
}
document.querySelector('#entryRetry').onclick=prepare;
window.addEventListener('focus',()=>{if(waitingForLogin)prepare()});
document.addEventListener('visibilitychange',()=>{if(!document.hidden&&waitingForLogin)prepare()});
prepare();
