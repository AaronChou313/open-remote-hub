'use strict';
const fragment=new URLSearchParams(location.hash.slice(1));
if(fragment.has('token')) {localStorage.setItem('orh-mesh-token',fragment.get('token'));history.replaceState(null,'',location.pathname);}
let token=localStorage.getItem('orh-mesh-token')||'';
async function refresh() {
  document.querySelector('#refresh').disabled=true;
  try {
    const response=await fetch('/api/v1/diagnostics',{headers:{Authorization:'Bearer '+token}});
    if(!response.ok) {document.querySelector('#tokenForm').hidden=false;throw Error('请使用本机组网凭据读取诊断');}
    document.querySelector('#tokenForm').hidden=true;
    document.querySelector('#notice').hidden=true;
    document.querySelector('#diagnostic').textContent=JSON.stringify(await response.json(),null,2);
  } catch(error) {document.querySelector('#notice').textContent=error.message;document.querySelector('#notice').hidden=false;}
  finally {document.querySelector('#refresh').disabled=false;}
}
document.querySelector('#refresh').onclick=refresh;
document.querySelector('#tokenForm').onsubmit=event=>{event.preventDefault();token=document.querySelector('#tokenInput').value.trim();localStorage.setItem('orh-mesh-token',token);refresh();};
refresh();
