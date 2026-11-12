/* Live service discovery, with direct Web links and saved application entries. */
'use strict';
window.RemoteHubLocalServices = (() => {
  let current = () => false;
  let data;
  let query = '';
  let kind = 'all';
  let includeInactive = false;
  let page = 0;
  let dialog;
  const pageSize = 40;
  const isWeb = endpoint => ['http','https'].includes(endpoint.protocol);
  const localBrowser = () => ['localhost','127.0.0.1','[::1]','::1'].includes(location.hostname);

  function entryUrl(endpoint) {
    if (endpoint.binding === 'loopback' && !localBrowser()) return null;
    const hostname = endpoint.binding === 'loopback' ? endpoint.address : location.hostname;
    return RemoteHubApplications.url({mode:'host',scheme:endpoint.protocol,port:endpoint.port,path:'/'},hostname);
  }

  async function render(check, force = false) {
    current = check;
    const result = await api('/local-services' + (force ? '?force=true' : ''));
    if (!check()) return;
    data = result;
    $('#content').innerHTML = `<section><div class="entry-toolbar service-toolbar"><input id="serviceSearch" type="search" aria-label="搜索本地服务" placeholder="搜索服务、进程或端口" value="${esc(query)}"><div class="entry-toolbar-actions"><select id="serviceKind" aria-label="服务类型">${[['all','全部服务'],['web','Web / HTTP'],['network','监听端口'],['background','后台服务']].map(([value,label])=>`<option value="${value}" ${kind===value?'selected':''}>${label}</option>`).join('')}</select><label class="service-inactive"><input type="checkbox" id="serviceInactive" ${includeInactive?'checked':''}>包括未运行服务</label></div></div><div id="serviceSummary" class="service-summary"></div>${result.warnings.map(warning=>`<p class="muted service-warning">${esc(warning)}</p>`).join('')}<div id="serviceEntries"></div><div id="servicePaging" class="service-paging"></div></section>`;
    $('#serviceSearch').oninput = event => { query = event.target.value; page = 0; draw(); };
    $('#serviceKind').onchange = event => { kind = event.target.value; page = 0; draw(); };
    $('#serviceInactive').onchange = event => { includeInactive = event.target.checked; page = 0; draw(); };
    draw();
  }

  function endpointMarkup(endpoint, index) {
    const address = endpoint.address === '*' ? '0.0.0.0' : endpoint.address;
    const label = `${address.includes(':')?'['+address+']':address}:${endpoint.port}`;
    if (!isWeb(endpoint)) return `<span class="service-tcp mono">${esc(label)}<small>TCP</small></span>`;
    const target = entryUrl(endpoint);
    return `<span class="service-web-entry">${target ? `<a href="${esc(target)}" target="_blank" rel="noopener" title="${esc(endpoint.protocol.toUpperCase()+' '+endpoint.http_status)}">${esc(endpoint.protocol.toUpperCase())} :${endpoint.port}${icon('external')}</a>` : `<span title="仅在宿主机本地监听">${esc(endpoint.protocol.toUpperCase())} :${endpoint.port} · 仅本机</span>`}${me.role === 'admin' ? `<button data-service-add="${index}" type="button" aria-label="将端口 ${endpoint.port} 添加到我的应用" title="添加到我的应用">${icon('plus')}</button>` : ''}</span>`;
  }

  function draw() {
    const filtered = data.services.filter(row => (includeInactive || row.running) && (kind==='all' || kind==='web' && row.endpoints.some(isWeb) || kind==='network' && row.endpoints.length || kind==='background' && !row.endpoints.length) && `${row.name} ${row.process?.name || ''} ${(row.process?.command || []).join(' ')} ${row.pid || ''} ${row.endpoints.map(item=>item.address+':'+item.port).join(' ')}`.toLowerCase().includes(query.toLowerCase()));
    page = Math.min(page,Math.max(0,Math.ceil(filtered.length/pageSize)-1));
    const rows = filtered.slice(page*pageSize,(page+1)*pageSize);
    const running = data.services.filter(row=>row.running);
    $('#serviceSummary').textContent = `${running.filter(row=>row.endpoints.some(isWeb)).length} 个 Web / HTTP 服务 · ${running.filter(row=>row.endpoints.length).length} 个监听服务 · ${running.length} 个运行中服务`;
    $('#serviceEntries').innerHTML = rows.length ? `<div class="table-wrap service-table"><table><thead><tr><th>服务</th><th>访问入口 / 监听端口</th><th>进程</th><th>来源</th><th>操作</th></tr></thead><tbody>${rows.map((row,index)=>`<tr data-service="${row.id}"><td class="service-name"><strong title="${esc(row.name)}">${esc(row.name.startsWith('application.') && row.process?.name ? row.process.name : row.name)}</strong>${row.process?.name ? `<small>${esc(row.process.name)}</small>` : ''}<span class="service-state ${row.running?'service-running':''}">${row.running?'运行中':'未运行'}</span></td><td><div class="service-endpoints">${row.endpoints.length ? row.endpoints.map((endpoint,number)=>endpointMarkup(endpoint,number)).join('') : '<span class="muted">—</span>'}</div></td><td class="service-process">${row.pid?`<span class="mono">PID ${row.pid}</span>`:'—'}${row.created?`<small>${uptime(Date.now()/1000-row.created)}</small>`:''}${row.process?.command?.length?`<code title="${esc(row.process.command.join(' '))}">${esc(row.process.command.join(' '))}</code>`:''}</td><td><span>${esc(row.source)}</span><small>${row.scope==='system'?'系统':row.scope==='container'?'容器':'用户'}</small></td><td><button data-service-detail="${index}">详情与日志</button></td></tr>`).join('')}</tbody></table></div>` : empty('没有匹配的本地服务');
    $('#servicePaging').innerHTML = `<span class="muted">${filtered.length} 个匹配服务 · 更新于 ${new Date(data.time*1000).toLocaleTimeString()}</span>${filtered.length>pageSize?`<div><button id="servicePrevious" ${page===0?'disabled':''}>上一页</button><span>${page+1} / ${Math.ceil(filtered.length/pageSize)}</span><button id="serviceNext" ${(page+1)*pageSize>=filtered.length?'disabled':''}>下一页</button></div>`:''}`;
    if ($('#servicePrevious')) $('#servicePrevious').onclick = () => { page--; draw(); };
    if ($('#serviceNext')) $('#serviceNext').onclick = () => { page++; draw(); };
    $('#serviceEntries').querySelectorAll('[data-service-detail]').forEach(button => { button.onclick = () => inspect(rows[Number(button.dataset.serviceDetail)],button).catch(showError); });
    $('#serviceEntries').querySelectorAll('[data-service-add]').forEach(button => {
      button.onclick = () => {
        const row = rows.find(item=>item.id===button.closest('[data-service]').dataset.service);
        const endpoint = row.endpoints[Number(button.dataset.serviceAdd)];
        RemoteHubApplications.addFromService({...endpoint,name:row.name.startsWith('application.') && row.process?.name ? row.process.name : row.name});
      };
    });
  }

  async function inspect(row, button) {
    const owner = current;
    await withBusy(button,'service:detail:'+row.id,'读取中…',async()=>{
      const detail = await api('/local-services/'+encodeURIComponent(row.id));
      if (!owner()) return;
      if (!dialog) {
        dialog=document.createElement('dialog');dialog.className='entry-dialog service-dialog';
        dialog.setAttribute('aria-labelledby','serviceDialogTitle');document.body.append(dialog);
      }
      const process = detail.process || {};
      const logs = detail.details?.logs || {};
      dialog.innerHTML = `<div class="detail-dialog-bar"><h2 id="serviceDialogTitle">${esc(detail.name)}</h2><button data-service-close>${icon('close')}关闭</button></div><dl class="service-definition"><dt>来源</dt><dd>${esc(detail.source)} · ${detail.scope==='system'?'系统':detail.scope==='container'?'容器':'用户'}</dd><dt>PID</dt><dd>${detail.pid || '—'}</dd><dt>用户</dt><dd>${esc(process.username || '不可读取')}</dd><dt>启动时间</dt><dd>${detail.created?new Date(detail.created*1000).toLocaleString():'—'}</dd><dt>工作目录</dt><dd class="mono">${esc(process.cwd || '不可读取')}</dd><dt>启动命令</dt><dd><code>${esc((process.command?.length ? process.command : detail.details?.command || []).join(' ')) || '不可读取'}</code></dd></dl>${detail.endpoints.length?`<h3>监听端口</h3><div class="service-detail-endpoints">${detail.endpoints.map(item=>`<p><code>${esc(item.address)}:${item.port}</code>${item.target?' → '+esc(item.target):''}</p>`).join('')}</div>`:''}${Object.entries(logs).map(([name,content])=>`<details class="service-log" open><summary>${esc(name)}</summary><pre>${esc(typeof content==='string'?content:JSON.stringify(content,null,2))}</pre></details>`).join('')}${detail.details?.note?`<p class="muted entry-form-note">${esc(detail.details.note)}</p>`:''}`;
      dialog.querySelector('[data-service-close]').onclick=()=>dialog.close();
      dialog.showModal();
    });
  }

  function reset(){current=()=>false;if(dialog?.open)dialog.close();}
  return {render,reset,isOpen:()=>Boolean(dialog?.open),entryUrl};
})();
