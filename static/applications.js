/* Saved Web entries with direct navigation and host-relative addresses. */
'use strict';
window.RemoteHubApplications = (() => {
  let current = () => false;
  let dialog;
  let saving = false;
  let query = '';
  let category = '';
  let applications = [];

  function url(entry, hostname = location.hostname) {
    if (entry.mode === 'custom') return entry.url;
    const host = hostname.includes(':') && !hostname.startsWith('[') ? '[' + hostname + ']' : hostname;
    return new URL(entry.path || '/', `${entry.scheme || 'http'}://${host}:${entry.port}/`).href;
  }

  async function render(check) {
    current = check;
    const data = await api('/applications');
    if (!check()) return;
    applications = data.applications;
    const groups = [...new Set(applications.map(entry => entry.group).filter(Boolean))].sort();
    if (!groups.includes(category)) category = '';
    $('#content').innerHTML = `<section><div class="entry-toolbar"><input id="appSearch" type="search" aria-label="搜索应用" placeholder="搜索应用名称、分组或地址" value="${esc(query)}"><div class="entry-toolbar-actions"><select id="appGroup" aria-label="应用分组"><option value="">所有分组</option>${groups.map(group => `<option ${group === category ? 'selected' : ''}>${esc(group)}</option>`).join('')}</select>${me.role === 'admin' ? `<button class="primary" id="appAdd">${icon('plus')}添加应用</button>` : ''}</div></div><div id="appEntries"></div></section>`;
    $('#appSearch').oninput = event => { query = event.target.value; draw(); };
    $('#appGroup').onchange = event => { category = event.target.value; draw(); };
    if ($('#appAdd')) $('#appAdd').onclick = () => edit();
    draw();
  }

  function draw() {
    const rows = applications.filter(entry => (!category || entry.group === category) && `${entry.name} ${entry.group} ${url(entry)}`.toLowerCase().includes(query.toLowerCase()));
    $('#appEntries').innerHTML = rows.length ? `<div class="application-grid">${rows.map(entry => `<article class="application-card" data-application="${entry.id}"><div class="application-heading"><span>${icon('applications')}</span><h2>${esc(entry.name)}</h2>${entry.group ? `<small>${esc(entry.group)}</small>` : ''}</div><p class="application-address mono">${esc(url(entry))}</p><div class="application-actions"><a class="button primary" href="${esc(url(entry))}" target="_blank" rel="noopener">${icon('external')}打开应用</a>${me.role === 'admin' ? `<button data-application-action="edit">${icon('rename')}编辑</button><button data-application-action="remove" class="danger">${icon('delete')}移除</button>` : ''}</div></article>`).join('')}</div>` : empty(query || category ? '没有匹配的应用' : '添加常用 Web 服务，或从“本地服务”中添加入口。');
    $('#appEntries').querySelectorAll('[data-application-action]').forEach(button => {
      button.onclick = async () => {
        const entry = rows.find(item => item.id === button.closest('[data-application]').dataset.application);
        try {
          if (button.dataset.applicationAction === 'edit') edit(entry);
          else {
            await withBusy(button, 'application:remove:' + entry.id, '移除中…', () => api(`/applications/${entry.id}/remove`, {revision:entry.revision}));
            if (current()) await render(current);
            notify('应用入口已移除');
          }
        } catch (error) { showError(error); }
      };
    });
  }

  function edit(entry, preset = {}) {
    if (!dialog) {
      dialog = document.createElement('dialog');
      dialog.className = 'entry-dialog';
      dialog.setAttribute('aria-labelledby','applicationDialogTitle');
      document.body.append(dialog);
      dialog.addEventListener('cancel', event => { if (saving) event.preventDefault(); });
    }
    const value = entry || {name:preset.name || '', mode:'host', scheme:preset.protocol || 'http', port:preset.port || '', path:'/', group:''};
    dialog.innerHTML = `<form><div class="detail-dialog-bar"><h2 id="applicationDialogTitle">${entry ? '编辑应用' : '添加应用'}</h2><button type="button" data-close>${icon('close')}关闭</button></div>
      <label>名称<input name="name" value="${esc(value.name)}" required maxlength="100" autocomplete="off"></label>
      <label for="appMode">访问地址</label><select id="appMode" name="mode"><option value="host" ${value.mode === 'host' ? 'selected' : ''}>当前主机端口</option><option value="custom" ${value.mode === 'custom' ? 'selected' : ''}>自定义网址</option></select>
      <div data-host-fields><div class="entry-form-grid"><label>协议<select name="scheme"><option value="http" ${value.scheme === 'http' ? 'selected' : ''}>HTTP</option><option value="https" ${value.scheme === 'https' ? 'selected' : ''}>HTTPS</option></select></label><label>端口<input name="port" type="number" min="1" max="65535" value="${esc(value.port || '')}" placeholder="例如 3000"></label></div><label>路径<input name="path" value="${esc(value.path || '/')}" placeholder="/"></label></div>
      <label data-custom-fields>网址<input name="url" type="url" value="${esc(value.url || '')}" placeholder="https://example.com/"></label>
      <label>分组<input name="group" maxlength="80" value="${esc(value.group || '')}" placeholder="可选"></label><p id="appUrlPreview" class="entry-url-preview mono"></p>${preset.binding === 'loopback' ? '<p class="muted entry-form-note">此服务仅监听宿主机回环地址，远程直连需在该服务中启用局域网监听。</p>' : ''}<p class="entry-form-error" role="alert" hidden></p><div class="dialog-actions"><button class="primary" type="submit">${entry ? '保存' : '添加应用'}</button></div></form>`;
    const form = dialog.querySelector('form');
    const update = () => {
      const custom = form.elements.mode.value === 'custom';
      dialog.querySelector('[data-host-fields]').hidden = custom;
      dialog.querySelector('[data-custom-fields]').hidden = !custom;
      form.elements.port.required = !custom;
      form.elements.url.required = custom;
      form.elements.url.disabled = !custom;
      for (const name of ['scheme','port','path']) form.elements[name].disabled = custom;
      try {
        const values = Object.fromEntries(new FormData(form));
        $('#appUrlPreview').textContent = custom ? values.url : values.port ? url(values) : '主机地址随当前控制台访问地址变化';
      } catch { $('#appUrlPreview').textContent = ''; }
    };
    form.oninput = update;
    form.onchange = update;
    dialog.querySelector('[data-close]').onclick = () => { if (!saving) dialog.close(); };
    form.onsubmit = async event => {
      event.preventDefault();
      if (saving) return;
      const body = Object.fromEntries(new FormData(form));
      body.port = body.mode === 'host' ? Number(body.port) : null;
      const controls = [...form.querySelectorAll('input, select, button')];
      saving = true;
      controls.forEach(control => { control.disabled = true; });
      try {
        await api(entry ? '/applications/' + entry.id : '/applications', {...body, revision:entry?.revision});
        dialog.close();
        notify('应用入口已保存');
        if (current()) await render(current);
      } catch (error) {
        const output = dialog.querySelector('.entry-form-error');
        output.textContent = error.message;
        output.hidden = false;
      } finally { saving = false; controls.forEach(control => { control.disabled = false; }); update(); }
    };
    update();
    dialog.showModal();
    form.elements.name.focus();
  }

  function canLeave() { return !saving; }
  function reset() { if (dialog?.open) dialog.close(); current = () => false; }
  return {render, url, addFromService:preset=>edit(null,preset), canLeave, reset, isOpen:()=>Boolean(dialog?.open)};
})();
