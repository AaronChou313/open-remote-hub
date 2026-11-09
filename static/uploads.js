'use strict';
window.RemoteHubUploads=(()=>{
 let active=null;
 function reset(){
  if(!active)return;
  active.disposed=true;
  active.cancelled=true;
  active.xhr?.abort();
  active=null;
 }
 function send(job,item){
  return new Promise((resolve,reject)=>{
   const xhr=new XMLHttpRequest();job.xhr=xhr;
   const params=new URLSearchParams({root:job.root,path:[job.path,item.path].filter(Boolean).join('/'),create_parents:String(job.folder)});
   xhr.open('POST','/api/files/upload?'+params);
   xhr.setRequestHeader('X-ORH-Request','1');
   xhr.timeout=30*60*1000;
   xhr.upload.onprogress=event=>{
    if(job.disposed)return;
    $('#uploadProgress').value=job.completedBytes+event.loaded;
    $('#uploadCurrent').textContent=item.path+' · '+bytes(event.loaded)+' / '+bytes(item.file.size);
   };
   xhr.onload=()=>{
    if(xhr.status>=200&&xhr.status<300){resolve();return}
    let message='上传失败';
    try{const detail=JSON.parse(xhr.responseText).detail;message=typeof detail==='string'?detail:JSON.stringify(detail)}catch{}
    reject(Object.assign(Error(message),{status:xhr.status}));
   };
   xhr.onerror=()=>reject(Error('连接中断，可重试剩余文件'));
   xhr.ontimeout=()=>reject(Error('上传超时，可重试剩余文件'));
   xhr.onabort=()=>reject(Error('已取消'));
   xhr.send(item.file);
  });
 }
 async function batch(job){
  if(job.running||job.disposed)return;
  job.running=true;job.cancelled=false;
  const attempts=job.pending;job.pending=[];
  const close=$('#workspaceDetailClose');
  close.textContent='取消上传';close.disabled=false;
  $('#uploadRetry').hidden=true;$('#uploadFailures').replaceChildren();
  $('#workspaceDetailTitle').textContent=job.folder?'上传文件夹':'上传文件';
  try{
   for(let i=0;i<attempts.length;i++){
    const item=attempts[i];
    if(job.cancelled||job.disposed){job.pending=job.pending.concat(attempts.slice(i));break}
    $('#uploadSummary').textContent='已上传 '+job.completed+' / '+job.total+' 个文件';
    $('#uploadCurrent').textContent=item.path;
    try{
     await send(job,item);
     job.completed++;job.completedBytes+=item.file.size;
    }catch(error){
     item.error=error.message;job.pending.push(item);
     if(error.status===401){showLogin();break}
     // Conflicting names can be collected in one pass. Stop on connection,
     // permission, or server failures, retaining the rest for an explicit retry.
     if(error.status!==409){job.pending=job.pending.concat(attempts.slice(i+1));break}
    }
    if(!job.disposed)$('#uploadProgress').value=job.completedBytes;
   }
  }finally{
   job.running=false;job.xhr=null;
  }
  if(job.disposed)return;
  close.textContent='关闭';close.disabled=false;
  $('#uploadProgress').value=job.pending.length?job.completedBytes:Math.max(1,job.completedBytes);
  $('#workspaceDetailTitle').textContent=job.pending.length?'上传未全部完成':'上传完成';
  $('#uploadSummary').textContent='已上传 '+job.completed+' / '+job.total+' 个文件，共 '+bytes(job.completedBytes);
  $('#uploadCurrent').textContent=job.pending.length?'剩余 '+job.pending.length+' 个文件。已完成文件已保留，重试仅处理剩余项。':'';
  $('#uploadFailures').innerHTML=job.pending.length?'<ul>'+job.pending.slice(0,20).map(item=>'<li>'+esc(item.path)+' · '+esc(item.error||'尚未上传')+'</li>').join('')+'</ul>':'';
  $('#uploadRetry').hidden=!job.pending.length;
  try{await job.onRefresh()}catch(error){if(!job.disposed)showError(error)}
 }
 async function start({files,root,path,folder=false,onRefresh}){
  if(!files.length||active?.running)return;
  const pending=Array.from(files,file=>({file,path:folder?file.webkitRelativePath:file.name}));
  if(pending.some(item=>!item.path))throw Error('浏览器未提供文件夹相对路径，请使用支持文件夹上传的桌面浏览器');
  const job={root,path,folder,onRefresh,pending,total:pending.length,completed:0,completedBytes:0,running:false,cancelled:false,disposed:false,xhr:null};
  active=job;
  const totalBytes=pending.reduce((sum,item)=>sum+item.file.size,0);
  const dialog=$('#workspaceDetailDialog');
  $('#workspaceDetailBody').innerHTML='<p class="file-name">'+esc(path||'/')+'</p><progress id="uploadProgress" max="'+Math.max(1,totalBytes)+'" value="0" aria-label="文件上传进度"></progress><p id="uploadSummary" role="status" aria-live="polite"></p><p id="uploadCurrent" class="file-name muted"></p><div id="uploadFailures" class="upload-failures"></div><button id="uploadRetry" hidden>重试剩余文件</button>';
  const stop=()=>{
   if(!job.running){dialog.close();return}
   job.cancelled=true;job.xhr?.abort();
   $('#workspaceDetailClose').disabled=true;
  };
  $('#workspaceDetailClose').onclick=stop;
  dialog.oncancel=event=>{if(job.running){event.preventDefault();stop()}};
  $('#uploadRetry').onclick=()=>batch(job);
  if(!dialog.open)dialog.showModal();
  await batch(job);
 }
 return {start,reset,isUploading:()=>!!active?.running};
})();
