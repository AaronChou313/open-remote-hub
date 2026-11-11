/* Host-local SSH operations. Secrets exist only in focused forms and requests. */
'use strict';
window.RemoteHubSSH = (() => {
  let tab = 'connections';
  let overview;
  let current = () => false;
  let dialog;
  let dialogEpoch = 0;
  let dirty = false;
  let query = '';
  let group = '';
  let favorites = false;
  let activeJob;
  let renderEpoch = 0;
  let submitting = false;
  let effectiveRequests = new Map();

  const encode = encodeURIComponent;
  const button = (action, label, attributes = '') => `<button type="button" data-ssh="${action}" ${attributes}>${label}</button>`;
  const actionButton = (action, label, glyph, attributes = '') => button(action, `${icon(glyph)}<span>${label}</span>`, attributes);
  const field = (name, label, value = '', attributes = '') => `<label>${label}<input name="${name}" value="${esc(value)}" ${attributes}></label>`;
  const errorBox = '<p class="ssh-error" role="alert" hidden></p>';

  function ensureDialog() {
    if (dialog) return;
    dialog = document.createElement('dialog');
    dialog.className = 'ssh-dialog';
    dialog.setAttribute('aria-labelledby', 'sshDialogTitle');
    document.body.append(dialog);
    dialog.addEventListener('close', () => {
      if (dialog.open) return;
      dialogEpoch++;
      dirty = false;
      dialog.replaceChildren();
      if (activeJob) {
        api(`/ssh/jobs/${activeJob}/cancel`, {}).catch(() => {});
        activeJob = null;
      }
    });
    dialog.addEventListener('cancel', event => {
      if (submitting) { event.preventDefault(); return; }
      if (dirty) {
        event.preventDefault();
        leaveDialog();
      }
    });
  }

  async function leaveDialog() {
    if (submitting) return false;
    if (dirty && !await confirmAction('放弃未保存修改？', '关闭后将丢弃此窗口中的编辑内容。')) return false;
    submitting = false; dialog.close();
    return true;
  }

  async function open(title, content) {
    ensureDialog();
    if (submitting) return null;
    if (dialog.open && dirty && !await confirmAction('放弃未保存修改？', '切换后将丢弃此窗口中的编辑内容。')) return null;
    dirty = false;
    if (activeJob) {
      api(`/ssh/jobs/${activeJob}/cancel`, {}).catch(() => {});
      activeJob = null;
    }
    dialog.innerHTML = `<div class="detail-dialog-bar"><h2 id="sshDialogTitle">${esc(title)}</h2>${button('close', `${icon('close')}关闭`)}</div>${errorBox}<div class="ssh-dialog-body">${content}</div>`;
    dialog.querySelector('[data-ssh="close"]').onclick = leaveDialog;
    if (!dialog.open) dialog.showModal();
    return ++dialogEpoch;
  }

  function showDialogError(error) {
    if (error.stale) return;
    const target = dialog?.querySelector('.ssh-error');
    if (target) {
      target.hidden = false;
      target.textContent = error.message;
    }
  }

  function form(content, submit) {
    return `<form class="ssh-form">${content}<div class="dialog-actions"><button class="primary" type="submit">${submit}</button></div></form>`;
  }

  function attachForm(work, track = true) {
    const target = dialog.querySelector('form');
    target.querySelector('input, select, textarea')?.focus({preventScroll:true});
    target.oninput = () => { if (track) dirty = true; };
    target.onsubmit = event => {
      event.preventDefault();
      return withBusy(event.submitter, 'ssh:dialog:' + dialogEpoch, '处理中…', async () => {
        const epoch = dialogEpoch;
        const controls = [...dialog.querySelectorAll('input, textarea, select, button')];
        const states = controls.map(control => control.disabled);
        try {
          const values = Object.fromEntries(new FormData(target));
          submitting = true;
          controls.forEach(control => { control.disabled = true; });
          await work(values, target);
        } catch (error) {
          if (epoch === dialogEpoch) showDialogError(error);
        } finally {
          if (epoch === dialogEpoch) {
            submitting = false;
            controls.forEach((control, index) => { control.disabled = states[index]; });
          }
        }
      });
    };
  }

  async function request(path, body) {
    const epoch = dialog?.open ? dialogEpoch : null;
    try {
      const result = await api(path, body);
      if (epoch !== null && epoch !== dialogEpoch) throw Object.assign(Error('窗口已关闭'), {stale: true});
      return result;
    } catch (error) {
      if (epoch !== null && epoch !== dialogEpoch) throw Object.assign(Error('窗口已关闭'), {stale: true});
      throw error;
    }
  }

  async function actionDialog(title, impact, work, content = '') {
    if (!await open(title, form(`<p>${esc(impact)}</p>${content}`, title))) return;
    attachForm(async values => { await work(values); }, false);
  }

  async function reload() {
    if (current()) await render(current);
  }

  async function render(isCurrent) {
    current = isCurrent;
    const version = ++renderEpoch;
    const data = await request('/ssh/overview');
    if (!isCurrent() || version !== renderEpoch) return;
    overview = data;
    effectiveRequests = new Map();
    $('#content').innerHTML = `<section class="ssh-center"><div class="ssh-tabs" role="tablist" aria-label="SSH 管理">${[
      ['connections', '连接管理'], ['keys', '密钥管理'], ['config', 'SSH 配置']
    ].map(([key, label]) => `<button type="button" role="tab" id="ssh-tab-${key}" aria-selected="${tab === key}" tabindex="${tab === key ? 0 : -1}" aria-controls="sshPanel" data-tab="${key}">${icon(key === 'connections' ? 'terminal' : key === 'keys' ? 'key' : 'settings')}${label}</button>`).join('')}</div><div id="sshPanel" role="tabpanel" aria-labelledby="ssh-tab-${tab}" tabindex="0"></div></section>`;
    document.querySelectorAll('[data-tab]').forEach(control => {
      control.onclick = async () => {
        if (!await canLeave()) return;
        tab = control.dataset.tab;
        await reload();
      };
      control.onkeydown = async event => {
        if (!['ArrowLeft', 'ArrowRight', 'Home', 'End'].includes(event.key)) return;
        event.preventDefault();
        const controls = [...document.querySelectorAll('[data-tab]')];
        let index = controls.indexOf(control) + (event.key === 'ArrowRight' ? 1 : -1);
        if (event.key === 'Home') index = 0;
        if (event.key === 'End') index = controls.length - 1;
        const next = controls[(index + controls.length) % controls.length].dataset.tab;
        if (!await canLeave()) return;
        tab = next;
        await reload();
        document.querySelector(`[data-tab="${next}"]`)?.focus();
      };
    });
    if (tab === 'connections') renderConnections();
    if (tab === 'keys') await renderKeys(version);
    if (tab === 'config') await renderConfig(version);
  }

  function renderConnections() {
    const groups = [...new Set(overview.connections.map(row => row.metadata?.group ?? row.group ?? '').filter(Boolean))].sort();
    $('#sshPanel').innerHTML = `${!overview.linked && overview.connections.some(row => row.managed) ? '<div class="ssh-attention"><p>受管连接尚未接入原生 Config</p><button id="sshIncludePreview">预览并接入</button></div>' : ''}<div class="ssh-toolbar"><input id="sshSearch" type="search" aria-label="搜索 SSH 连接" placeholder="搜索别名、地址或分组" value="${esc(query)}"><select id="sshGroup" aria-label="筛选分组"><option value="">所有分组</option>${groups.map(name => `<option value="${esc(name)}" ${group === name ? 'selected' : ''}>${esc(name)}</option>`).join('')}</select><button id="sshFavorites" aria-pressed="${favorites}">仅收藏</button><button id="sshNew" class="primary">${icon('plus')}新建连接</button></div><div id="sshConnections"></div>`;
    $('#sshSearch').oninput = event => { query = event.target.value; drawConnections(); };
    $('#sshGroup').onchange = event => { group = event.target.value; drawConnections(); };
    $('#sshFavorites').onclick = event => { favorites = !favorites; event.currentTarget.setAttribute('aria-pressed', favorites); drawConnections(); };
    $('#sshNew').onclick = () => connectionForm().catch(showDialogError);
    const include = $('#sshIncludePreview');
    if (include) include.onclick = async () => {
      try { await applyPlan(await request('/ssh/config/plan', {action:'include'})); }
      catch (error) { showError(error); }
    };
    drawConnections();
  }

  function connectionFacts(row, values = row) {
    const authentication = row.authentication === 'password' ? '密码' : row.authentication === 'key' ? '密钥' : '原生配置';
    const identities = row.identityfile || (values.identityfile?.length === 1 ? values.identityfile[0] : '');
    return `<p class="ssh-card-address mono">${esc(values.hostname || row.alias)}</p>
      <dl class="ssh-card-facts"><div><dt>用户名</dt><dd>${esc(values.user || '系统默认')}</dd></div><div><dt>端口</dt><dd>${esc(values.port || '22')}</dd></div><div><dt>认证</dt><dd>${authentication}</dd></div></dl>
      ${identities && row.authentication !== 'password' ? `<p class="ssh-card-path" title="${esc(identities)}">${icon('key')}<span>${esc(identities)}</span></p>` : ''}
      ${values.proxyjump && values.proxyjump !== 'none' ? `<p class="ssh-card-path">${icon('network')}<span>经由 ${esc(values.proxyjump)}</span></p>` : ''}`;
  }

  function drawConnections() {
    const entries = overview.connections.filter(row => {
      const category = row.metadata?.group ?? row.group ?? '';
      const favorite = row.metadata?.favorite ?? row.favorite ?? false;
      return (!group || category === group) && (!favorites || favorite) &&
        `${row.alias} ${row.hostname || ''} ${category}`.toLowerCase().includes(query.toLowerCase());
    });
    $('#sshConnections').innerHTML = entries.length ? `<div class="ssh-connections">${entries.map(row => {
      const category = row.metadata?.group ?? row.group ?? '';
      const favorite = row.metadata?.favorite ?? row.favorite ?? false;
      const sessions = overview.sessions.filter(session => session.host.toLowerCase() === row.alias.toLowerCase());
      const live = sessions.filter(session => session.running);
      return `<article class="ssh-connection" data-host="${esc(row.alias)}">
        <div class="ssh-card-heading"><span class="ssh-card-glyph">${icon('terminal')}</span><div><h2>${esc(row.alias)}</h2><span class="muted">${row.managed ? '自建连接' : 'SSH Config'}</span></div><button class="ssh-star" data-ssh="favorite" aria-label="${favorite ? '取消收藏' : '收藏'} ${esc(row.alias)}" aria-pressed="${favorite}">${icon('star')}</button></div>
        <div class="ssh-card-info">${row.managed ? connectionFacts(row) : '<p class="muted ssh-card-loading">正在读取连接信息…</p>'}</div>
        <div class="ssh-connection-status">${category ? `<span>${icon('folder')}${esc(category)}</span>` : ''}${live.length ? `<span class="ssh-online"><i class="ssh-status-dot"></i>${live.length} 个连接中</span>` : ''}${row.duplicate ? '<span class="danger-text">重复 Host</span>' : ''}</div>
        ${sessions.some(session => session.live_session) ? `<div class="ssh-card-sessions">${sessions.filter(session => session.live_session).map(session => `<a href="/terminal/${encode(session.session)}" target="_blank" rel="noopener" class="ssh-session-link">${icon('terminal')}<span>${esc(session.session)}</span><span class="muted">${session.running ? '连接中' : '已退出'}</span>${icon('external')}</a>`).join('')}</div>` : ''}
        <div class="ssh-card-primary">${actionButton('connect', live.length ? '进入终端' : '连接', 'terminal', 'class="primary"')}${actionButton('new', '新开终端', 'plus')}</div>
        <div class="ssh-card-tools">${actionButton('edit', '编辑', 'rename')}${actionButton('organize', '分组', 'folder')}${actionButton('diagnose', '诊断', 'diagnose')}${actionButton('fingerprint', '主机指纹', 'fingerprint')}${actionButton('deploy', '部署公钥', 'upload')}${row.managed ? actionButton('delete', '删除', 'delete', 'class="danger"') : ''}</div>
        <details class="ssh-effective-options"><summary>OpenSSH 生效选项${icon('chevron')}</summary><div class="ssh-effective-values muted">正在读取…</div></details>
      </article>`;
    }).join('')}</div>` : empty(query || group || favorites ? '没有匹配的 SSH 连接' : '暂无 SSH 连接');
    $('#sshConnections').onclick = async event => {
      const control = event.target.closest('[data-ssh]');
      if (!control) return;
      const owner = current;
      const row = overview.connections.find(item => item.alias === control.closest('[data-host]').dataset.host);
      try { await connectionAction(control.dataset.ssh, row, control); }
      catch (error) { if (owner()) showError(error); }
    };
    $('#sshConnections').querySelectorAll('[data-host]').forEach(card => {
      const row = entries.find(item => item.alias === card.dataset.host);
      if (!effectiveRequests.has(row.alias)) {
        effectiveRequests.set(row.alias, api(`/ssh/connections/${encode(row.alias)}/effective`).then(values => ({values}), error => ({error})));
      }
      effectiveRequests.get(row.alias).then(({values, error}) => {
        if (!card.isConnected || !current()) return;
        if (error) {
          if (!row.managed) card.querySelector('.ssh-card-info').innerHTML = `<p class="ssh-card-address mono">${esc(row.alias)}</p>`;
          card.querySelector('.ssh-effective-values').textContent = error.message;
          return;
        }
        card.querySelector('.ssh-card-info').innerHTML = connectionFacts(row, values);
        const names = {hostname:'主机地址', user:'用户名', port:'端口', identityfile:'身份密钥', proxyjump:'跳板', identityagent:'SSH Agent', forwardagent:'Agent 转发', identitiesonly:'仅指定密钥', stricthostkeychecking:'主机身份校验', userknownhostsfile:'主机指纹文件', hostkeyalias:'主机密钥别名', preferredauthentications:'认证顺序', pubkeyauthentication:'公钥认证', passwordauthentication:'密码认证', kbdinteractiveauthentication:'交互式认证'};
        card.querySelector('.ssh-effective-values').innerHTML = `<dl class="ssh-definition">${Object.entries(values).map(([key, value]) => `<dt>${esc(names[key] || key)}</dt><dd class="mono">${esc([].concat(value).join('\n'))}</dd>`).join('')}</dl>`;
      });
    });
  }

  async function connectionAction(action, row, control) {
    const owner = current;
    if (action === 'connect' || action === 'new') return connect(row.alias, control, action === 'new');
    if (action === 'edit') return row.managed ? connectionForm(row) : editConfig(row.sources[0].file);
    if (action === 'organize') return organize(row);
    if (action === 'diagnose') return diagnose(row.alias);
    if (action === 'fingerprint') return fingerprints(row.alias);
    if (action === 'deploy') return deploy(row.alias);
    if (action === 'favorite') {
      const favorite = row.metadata?.favorite ?? row.favorite ?? false;
      const result = await withBusy(control, 'ssh:favorite:' + row.alias, '…', () => api('/ssh/connections/metadata', {alias: row.alias, group: row.metadata?.group ?? row.group ?? '', favorite: !favorite}));
      if (!owner()) return;
      if (result?.revision) row.revision = result.revision;
      row.metadata = {...row.metadata, favorite: !favorite};
      drawConnections();
    }
    if (action === 'delete' && await confirmAction('删除连接 ' + row.alias + '？', '移除该连接的 SSH 配置，已打开的终端继续运行。')) {
      await withBusy(control, 'ssh:delete:' + row.alias, '删除中…', () => api('/ssh/connections/delete', {alias: row.alias, confirm: row.alias, connection_revision: row.revision, managed_revision: overview.managed_revision}));
      if (owner()) await reload();
    }
  }

  async function connect(host, control, newSession = false, key) {
    if (pendingOperations.has('ssh:connect:' + host)) return;
    const owner = current;
    const epoch = dialog?.open ? dialogEpoch : null;
    const target = window.open('about:blank', '_blank');
    if (!target) throw Error('浏览器阻止了新标签页，请允许此站点弹出终端');
    target.opener = null;
    try {
      await withBusy(control, 'ssh:connect:' + host, '准备终端…', async () => {
        const endpoint = `/ssh/connections/${encode(host)}/${key ? 'deploy' : 'connect'}`;
        const result = await request(endpoint, key ? {key} : {new: newSession});
        if (!target.closed) target.location.replace(result.url);
        if (epoch !== null && epoch === dialogEpoch && dialog?.open) { dirty = false; submitting = false; dialog.close(); }
        if (owner()) await reload();
      });
    } catch (error) { target.close(); throw error; }
  }

  async function connectionForm(row) {
    const epoch = await open(row ? '编辑 ' + row.alias : '新建 SSH 连接', '<p>读取设置…</p>');
    if (!epoch) return;
    const [data, initialIncludePlan] = await Promise.all([
      request('/ssh/keys'),
      overview.linked ? null : request('/ssh/config/plan', {action:'include'})
    ]);
    if (epoch !== dialogEpoch) return;
    let includePlan = initialIncludePlan;
    const authentication = row?.authentication || (row ? 'auto' : 'password');
    let savedRow = row;
    let managedRevision = overview.managed_revision;
    dialog.querySelector('.ssh-dialog-body').innerHTML = form(`
      <section class="ssh-form-section"><h3>基本设置</h3><div class="ssh-form-grid">
        ${field('alias', '连接名称', row?.alias, 'required maxlength="80" pattern="[A-Za-z0-9][A-Za-z0-9_.-]*" placeholder="例如 dev-server"')}
        ${field('hostname', '主机地址', row?.hostname, 'required maxlength="253" placeholder="IP 地址或域名"')}
        ${field('user', '用户名', row?.user, 'maxlength="80" placeholder="留空使用当前系统用户名"')}
        ${field('port', '端口', row?.port || '22', 'type="number" min="1" max="65535" required')}
      </div>
      <fieldset class="ssh-authentication"><legend>认证方式</legend><div class="ssh-auth-options">
        ${[['password','密码连接','lock'],['key','密钥连接','key'],...(row ? [['auto','沿用原生配置','settings']] : [])].map(([value,label,glyph]) => `<label><input type="radio" name="authentication" value="${value}" ${authentication === value ? 'checked' : ''}><span>${icon(glyph)}${label}</span></label>`).join('')}
      </div></fieldset>
      <p class="muted ssh-auth-note" data-auth-password ${authentication === 'password' ? '' : 'hidden'}>连接后在终端中输入目标主机密码。</p>
      <label data-auth-key ${authentication === 'key' ? '' : 'hidden'}>身份密钥<select name="identityfile"><option value="">使用系统默认密钥 / SSH Agent</option>${data.keys.filter(key => key.private && !key.unavailable).map(key => {
        const path = overview.directory + '/' + key.name;
        return `<option value="${esc(path)}" ${row?.identityfile === path ? 'selected' : ''}>${esc(key.name)}</option>`;
      }).join('')}</select></label></section>
      <details class="ssh-form-advanced"><summary>${icon('settings')}高级设置${icon('chevron')}</summary><div class="ssh-form-grid">
        ${field('group', '分组', row?.metadata?.group ?? row?.group)}
        ${field('proxyjump', '跳板 ProxyJump', row?.proxyjump, 'placeholder="可选，例如 jump-host"')}
        ${field('identityagent', 'SSH Agent', row?.identityagent, 'placeholder="SSH_AUTH_SOCK、none 或 Socket 绝对路径"')}
        <label>转发 SSH Agent<select name="forwardagent"><option value="">原生默认</option><option value="no" ${row?.forwardagent === 'no' ? 'selected' : ''}>关闭</option><option value="yes" ${row?.forwardagent === 'yes' ? 'selected' : ''}>开启</option></select></label>
        <label>仅指定密钥<select name="identitiesonly"><option value="">原生默认</option><option value="yes" ${row?.identitiesonly === 'yes' ? 'selected' : ''}>是</option><option value="no" ${row?.identitiesonly === 'no' ? 'selected' : ''}>否</option></select></label>
      </div></details>
      ${includePlan?.diff ? `<details class="ssh-form-advanced"><summary>${icon('file')}同时接入原生 SSH Config${icon('chevron')}</summary><pre class="ssh-diff">${esc(includePlan.diff)}</pre></details>` : ''}
    `, row ? '保存连接' : includePlan?.diff ? '创建并接入' : '创建连接');
    const target = dialog.querySelector('form');
    function updateAuthentication() {
      const value = target.elements.authentication.value;
      target.querySelector('[data-auth-password]').hidden = value !== 'password';
      target.querySelector('[data-auth-key]').hidden = value === 'password';
      target.elements.identityfile.disabled = value === 'password';
    }
    target.querySelectorAll('[name="authentication"]').forEach(input => { input.onchange = updateAuthentication; });
    updateAuthentication();
    attachForm(async values => {
      if (includePlan?.diff) {
        const fresh = await request('/ssh/config/plan', {action:'include'});
        if (fresh.revision !== includePlan.revision) throw Error('SSH Config 已改变，请重新打开连接表单');
        includePlan = fresh;
      }
      savedRow = await request('/ssh/connections/save', {...values, favorite: row?.metadata?.favorite ?? row?.favorite ?? false,
        original_alias: savedRow?.alias, connection_revision: savedRow?.revision, managed_revision: managedRevision});
      managedRevision = savedRow.file.revision;
      if (includePlan?.diff) await request('/ssh/config/apply', {plan:includePlan.plan, confirm:includePlan.file});
      dirty = false;
      submitting = false; dialog.close();
      notify('SSH 连接已保存');
      await reload();
    });
  }

  async function organize(row) {
    if (!await open('设置分组', form(field('group', '分组名称', row.metadata?.group ?? row.group, 'maxlength="80"'), '保存分组'))) return;
    attachForm(async values => {
      await request('/ssh/connections/metadata', {alias: row.alias, group: values.group, favorite: row.metadata?.favorite ?? row.favorite ?? false});
      dirty = false;
      submitting = false; dialog.close();
      await reload();
    });
  }

  async function diagnose(host, kind = 'diagnose') {
    const epoch = await open(kind === 'scan' ? '核验主机指纹 · ' + host : '连接诊断 · ' + host,
      `<p id="sshJobStatus" role="status">正在开始检查…</p><div id="sshJobResult"></div>${button('cancel', '取消检查')}`);
    if (!epoch) return;
    const cancel = dialog.querySelector('[data-ssh="cancel"]');
    cancel.disabled = true;
    let job;
    try {
      job = await api(`/ssh/connections/${encode(host)}/diagnose`, {kind});
    } catch (error) {
      if (epoch === dialogEpoch) {
        showDialogError(error);
        dialog.querySelector('#sshJobStatus').textContent = '检查未启动';
      }
      return;
    }
    if (epoch !== dialogEpoch || !current()) { await api(`/ssh/jobs/${job.id}/cancel`, {}); return; }
    activeJob = job.id;
    cancel.disabled = false;
    cancel.onclick = async () => { await request(`/ssh/jobs/${job.id}/cancel`, {}); cancel.disabled = true; };
    while (epoch === dialogEpoch && current()) {
      const result = await request(`/ssh/jobs/${job.id}`);
      if (epoch !== dialogEpoch) return;
      dialog.querySelector('#sshJobStatus').textContent = result.stage;
      if (!['queued', 'running'].includes(result.state)) {
        activeJob = null;
        cancel.hidden = true;
        if (kind === 'scan' && result.state === 'completed') await showScan(host, result.result, epoch);
        else dialog.querySelector('#sshJobResult').innerHTML = `<p class="${result.result?.status === 'authenticated' ? 'ssh-online' : ''}">${esc(result.result?.message || result.stage)}</p>${result.checks ? `<pre>${esc(result.checks.map(check => check.kind + ' · ' + check.status).join('\n'))}</pre>` : ''}`;
        return;
      }
      await new Promise(resolve => setTimeout(resolve, 700));
    }
  }

  async function fingerprints(host) {
    const epoch = await open('主机指纹 · ' + host, '<p>正在读取…</p>');
    if (!epoch) return;
    const result = await request(`/ssh/hosts/${encode(host)}`);
    if (epoch !== dialogEpoch) return;
    dialog.querySelector('.ssh-dialog-body').innerHTML = `<p class="mono">${esc(result.label)}</p>${result.entries.length ? result.entries.map(entry => `<p><strong>${esc(entry.type)}</strong><br><code>${esc(entry.fingerprint)}</code></p>`).join('') : '<p>尚无已知主机指纹</p>'}${result.external_files.length ? `<p class="muted">此连接还使用外部指纹文件，由原生 OpenSSH 校验。</p>` : ''}<div class="ssh-row-actions">${button('scan', '扫描并核验')}${result.entries.length ? button('remove', '移除指纹', 'class="danger"') : ''}</div>`;
    dialog.querySelector('[data-ssh="scan"]').onclick = () => diagnose(host, 'scan').catch(showDialogError);
    const remove = dialog.querySelector('[data-ssh="remove"]');
    if (remove) remove.onclick = async () => {
      await actionDialog('移除主机指纹', `移除 ${result.label} 的已知指纹。下次连接需要重新核验身份。`, async () => {
        await request(`/ssh/hosts/${encode(host)}/remove`, {confirm:host, revision:result.revision});
        submitting = false;
        await fingerprints(host);
      });
    };
  }

  async function showScan(host, result, epoch) {
    if (epoch !== dialogEpoch) return;
    dialog.querySelector('#sshJobResult').innerHTML = form(`<p class="${result.changed ? 'danger-text' : ''}">${result.changed ? '服务器指纹发生变化。请先通过独立渠道核验身份。' : '请通过独立渠道核验以下指纹，再保存信任。'}</p><p class="mono">${esc(result.label)}</p>${result.keys.map(key => `<label class="ssh-checkbox"><input type="checkbox" name="fingerprints" value="${esc(key.fingerprint)}"><span>${esc(key.type)}<code>${esc(key.fingerprint)}</code></span></label>`).join('')}`, result.known.length ? '确认核验并更新指纹' : '确认核验并信任');
    attachForm(async (values, target) => {
      const fingerprints = [...target.querySelectorAll('[name="fingerprints"]:checked')].map(input => input.value);
      const payload = {scan_id:result.scan_id, confirm:result.label, replace:result.known.length > 0, fingerprints};
      await request('/ssh/hosts/trust', payload);
      dirty = false;
      submitting = false;
      notify('主机指纹已保存');
      await fingerprintsView();
    }, false);
    async function fingerprintsView() { await fingerprints(host); }
  }

  async function deploy(host) {
    const data = await request('/ssh/keys');
    const available = data.keys.filter(key => key.private && key.public);
    if (!available.length) throw Error('请先生成或导入包含公钥的本地密钥对');
    if (!await open('部署公钥 · ' + host, form(`<label>本地公钥<select name="key">${available.map(key => `<option value="${esc(key.name)}">${esc(key.name)} · ${esc(key.fingerprint)}</option>`).join('')}</select></label><p class="muted">在终端中输入目标设备密码或密钥口令。公钥将追加到 authorized_keys，随后验证公钥认证。</p>`, '部署并进入终端 ↗'))) return;
    attachForm(async (values, target) => { await connect(host, target.querySelector('button[type="submit"]'), true, values.key); }, false);
  }

  async function renderKeys(version) {
    const data = await request('/ssh/keys');
    if (!current() || version !== renderEpoch || tab !== 'keys') return;
    $('#sshPanel').innerHTML = `<div class="ssh-toolbar"><span class="muted">${data.keys.length} 个本地密钥</span><div class="ssh-row-actions"><button id="sshImport">${icon('upload')}导入密钥</button><button class="primary" id="sshGenerate">${icon('plus')}新建密钥</button></div></div>
      <div class="ssh-key-grid">${data.keys.length ? data.keys.map((key, index) => `<article class="ssh-key-card" data-key-index="${index}">
        <div class="ssh-card-heading"><span class="ssh-card-glyph">${icon('key')}</span><div><h2>${esc(key.name)}</h2><span class="muted">${esc(key.type || 'SSH 密钥')}${key.bits && key.type !== 'ED25519' ? ' · ' + key.bits + ' 位' : ''}</span></div>${key.unavailable ? '' : `<span class="ssh-key-protection">${icon(key.encrypted ? 'shield' : 'key')}${key.private ? key.encrypted ? '口令保护' : '无口令' : '仅公钥'}</span>`}</div>
        ${key.unavailable ? '<p class="danger-text">文件权限或格式不可读取</p>' : `
          <code class="ssh-fingerprint">${esc(key.fingerprint || '')}</code>
          ${key.public ? `<textarea class="ssh-public ssh-card-public" readonly aria-label="${esc(key.name)} 公钥" rows="2">${esc(key.public)}</textarea>` : '<p class="muted">尚无公钥，可从私钥生成。</p>'}
          <p class="ssh-key-references muted">关联连接正在检查…</p>
          <div class="ssh-key-actions">
            ${key.public ? actionButton('copy', '复制公钥', 'copy') + `<a class="button" href="/api/ssh/keys/${encode(key.name)}/public" download>${icon('download')}下载公钥</a>` : actionButton('derive', '生成公钥', 'key')}
            ${key.private ? actionButton('passphrase', '修改口令', 'password') + actionButton('export', '导出私钥', 'download') : ''}
            ${actionButton('delete', '删除密钥', 'delete', 'class="danger"')}
          </div>`}
      </article>`).join('') : empty('暂无 SSH 密钥')}</div>
      ${data.backups.length ? '<details class="ssh-backup-section"><summary>密钥备份与恢复 <span>' + data.backups.length + '</span></summary><div>' : ''}${data.backups.slice().reverse().map(backup => `<div class="ssh-config-file"><span>${esc(backup.file)}<small class="muted">${new Date(backup.created * 1000).toLocaleString()}</small></span>${button('key-restore', `${icon('restore')}恢复`, `data-backup="${backup.id}"`)}</div>`).join('')}${data.backups.length ? '</div></details>' : ''}`;
    $('#sshGenerate').onclick = () => generate().catch(showError);
    $('#sshImport').onclick = () => importKey().catch(showError);
    $('#sshPanel').querySelectorAll('[data-ssh="key-restore"]').forEach(control => {
      control.onclick = () => {
        const backup = data.backups.find(item => item.id === control.dataset.backup);
        actionDialog('恢复密钥备份', `恢复 ${backup.file} 的选定备份。当前文件将另存备份。`, async () => {
          await request('/ssh/backups/restore', {backup:backup.id, revision:data.revisions[backup.file], confirm:backup.file});
          submitting = false; dialog.close();
          await reload();
        }).catch(showError);
      };
    });
    $('#sshPanel').querySelectorAll('[data-key-index]').forEach(card => {
      const key = data.keys[Number(card.dataset.keyIndex)];
      if (key.unavailable) return;
      card.querySelectorAll('[data-ssh]').forEach(control => {
        control.onclick = () => keyAction(control.dataset.ssh, key, card, control).catch(showError);
      });
      api(`/ssh/keys/${encode(key.name)}/references`).then(result => {
        if (!card.isConnected || !current()) return;
        const names = result.connections.length ? result.connections : result.rules || [];
        card.querySelector('.ssh-key-references').textContent = names.length ? '关联连接 · ' + names.join('、') : result.unresolved.length ? '关联配置无法读取，请检查 SSH Config' : '无关联连接';
      }).catch(error => { if (card.isConnected) card.querySelector('.ssh-key-references').textContent = error.message; });
    });
  }

  async function generate() {
    if (!await open('新建 SSH 密钥', form(`
      ${field('name', '密钥名称', '', 'required pattern="[A-Za-z0-9][A-Za-z0-9_.-]*" maxlength="96" placeholder="例如 work-laptop"')}
      <div class="ssh-form-grid">
        <label>密钥类型<select name="algorithm" id="sshKeyAlgorithm">
          <option value="ed25519">ED25519</option><option value="rsa">RSA</option><option value="ecdsa">ECDSA</option>
        </select></label>
        <label id="sshKeyBitsField" hidden>密钥位数<select name="bits" id="sshKeyBits" disabled></select></label>
      </div>
      ${field('comment', '备注', '', 'maxlength="200" placeholder="用途或邮箱，可选"')}
      <div class="ssh-form-grid">
        ${field('passphrase', '密钥口令', '', 'type="password" autocomplete="new-password" placeholder="可选"')}
        ${field('again', '确认密钥口令', '', 'type="password" autocomplete="new-password"')}
      </div>`, '创建密钥'))) return;
    const algorithm = dialog.querySelector('#sshKeyAlgorithm');
    const bits = dialog.querySelector('#sshKeyBits');
    algorithm.onchange = () => {
      const choices = algorithm.value === 'rsa' ? [2048, 3072, 4096] : algorithm.value === 'ecdsa' ? [256, 384, 521] : [];
      bits.innerHTML = choices.map(value => `<option value="${value}" ${value === (algorithm.value === 'rsa' ? 4096 : 256) ? 'selected' : ''}>${value} 位</option>`).join('');
      bits.disabled = choices.length === 0;
      dialog.querySelector('#sshKeyBitsField').hidden = !choices.length;
    };
    attachForm(async values => {
      if (values.passphrase !== values.again) throw Error('两次口令不一致');
      await request('/ssh/keys/generate', values);
      dirty = false;
      submitting = false; dialog.close();
      notify('密钥已创建');
      await reload();
    });
    const target = dialog.querySelector('form');
    target.oninput = () => { dirty = ['name', 'comment', 'passphrase', 'again'].some(name => target.elements[name].value.length > 0); };
  }

  async function importKey() {
    if (!await open('导入 SSH 密钥', form(`${field('name', '保存名称', '', 'required maxlength="96"')}<label>私钥文件（可选）<input type="file" name="privateFile"></label><label>公钥文件（可选）<input type="file" name="publicFile" accept=".pub,text/plain"></label>${field('passphrase', '私钥口令（如已加密）', '', 'type="password" autocomplete="off"')}`, '导入密钥'))) return;
    attachForm(async (values, target) => {
      const privateFile = target.elements.privateFile.files[0];
      const publicFile = target.elements.publicFile.files[0];
      if (!privateFile && !publicFile) throw Error('请选择私钥或公钥文件');
      if ((privateFile?.size || 0) > 65536 || (publicFile?.size || 0) > 16384) throw Error('密钥文件过大');
      await request('/ssh/keys/import', {name: values.name, passphrase: values.passphrase, private: privateFile ? await privateFile.text() : '', public: publicFile ? await publicFile.text() : ''});
      dirty = false;
      submitting = false; dialog.close();
      notify('密钥已导入');
      await reload();
    });
  }

  async function copyPublic(text, selection) {
    if (window.isSecureContext && navigator.clipboard?.writeText) {
      try { await navigator.clipboard.writeText(text); return; }
      catch { /* Continue with the user-initiated HTTP-compatible copy path. */ }
    }
    const input = selection || dialog.querySelector('.ssh-public');
    input.focus();
    input.select();
    let wrote = false;
    const write = event => {
      if (!event.clipboardData) return;
      event.clipboardData.setData('text/plain', text);
      event.preventDefault();
      wrote = true;
    };
    document.addEventListener('copy', write, true);
    try {
      if (!document.execCommand('copy') || !wrote) throw Error('公钥已选中，请按 Ctrl+C、⌘C 或长按复制');
    } finally {
      document.removeEventListener('copy', write, true);
    }
  }

  async function keyAction(action, key, card, control) {
    if (action === 'copy') {
      await copyPublic(key.public, card.querySelector('.ssh-public'));
      notify('公钥已复制');
    }
    if (action === 'derive') {
      if (!await open('生成匹配公钥', form(field('passphrase', '私钥口令（如已加密）', '', 'type="password" autocomplete="off"'), '生成公钥'))) return;
      attachForm(async values => {
        await request(`/ssh/keys/${encode(key.name)}/recover-public`, values);
        submitting = false; dialog.close();
        await reload();
      });
    }
    if (action === 'export') {
      await withBusy(control, 'ssh:export:' + key.name, '导出中…', async () => {
        const response = await fetch(`/api/ssh/keys/${encode(key.name)}/export`, {method:'POST', headers:{'Content-Type':'application/json', 'X-ORH-Request':'1'}, body:'{}', signal:AbortSignal.timeout(10000)});
        if (!response.ok) throw Error((await response.json()).detail || '私钥导出失败');
        const blob = await response.blob();
        if (!card.isConnected || !current()) return;
        const url = URL.createObjectURL(blob);
        const anchor = document.createElement('a');
        anchor.href = url;
        anchor.download = key.name;
        anchor.click();
        setTimeout(() => URL.revokeObjectURL(url), 1000);
      });
    }
    if (action === 'passphrase') await actionDialog('修改密钥口令', `更新 ${key.name} 的加密口令。原文件将保留备份。`, async values => {
      if (values.passphrase !== values.again) throw Error('两次新口令不一致');
      await request(`/ssh/keys/${encode(key.name)}/passphrase`, {...values, revision:key.revision});
      submitting = false; dialog.close();
      await reload();
    }, `${key.encrypted !== false ? field('old_passphrase', '当前密钥口令', '', 'type="password" autocomplete="off"') : ''}${field('passphrase', '新密钥口令（留空则移除）', '', 'type="password" autocomplete="new-password"')}${field('again', '再次输入新口令', '', 'type="password" autocomplete="new-password"')}`);
    if (action === 'delete') await actionDialog('删除密钥', `删除 ${key.name} 及其公钥，文件将保留备份。`, async () => {
      await request(`/ssh/keys/${encode(key.name)}/delete`, {confirm:key.name, revision:key.revision, public_revision:key.public_revision});
      submitting = false; dialog.close();
      await reload();
    });
  }

  async function renderConfig(version) {
    const data = await request('/ssh/config');
    data.files.sort((a, b) => Number(b.relative === 'config') - Number(a.relative === 'config') || a.name.localeCompare(b.name));
    if (!current() || version !== renderEpoch || tab !== 'config') return;
    $('#sshPanel').innerHTML = `<div class="ssh-config-header"><div><h2>原生 SSH Config</h2><p class="mono muted">${esc(overview.directory)}</p></div>${!data.include.linked ? '<button class="primary" id="sshLink">接入原生 Config</button>' : '<span class="ssh-online">受管 Include 已接入</span>'}</div><div class="ssh-config-files">${data.files.map(file => `<div class="ssh-config-file"><div><strong>${esc(file.name)}</strong><p class="mono muted">${esc(file.path)}</p></div>${button('config-file', file.editable ? '查看 / 高级编辑' : '查看', `data-file="${file.id}"`)}</div>`).join('') || empty('尚无 SSH Config')}</div>${data.rules.length ? `<details class="ssh-rule-list"><summary>Host 模式规则 · ${data.rules.length}</summary><pre>${esc(data.rules.map(rule => rule.pattern).join('\n'))}</pre></details>` : ''}${data.warnings.map(warning => `<p class="danger-text">${esc(warning)}</p>`).join('')}${data.backups.length ? '<details class="ssh-backup-section"><summary>配置备份与恢复 <span>' + data.backups.length + '</span></summary><div class="ssh-backups">' : ''}${data.backups.slice().reverse().map(backup => `<div class="ssh-config-file"><span>${esc(backup.file)}<small class="muted">${new Date(backup.created * 1000).toLocaleString()}</small></span>${button('restore', '恢复', `data-backup="${backup.id}"`)}</div>`).join('')}${data.backups.length ? '</div></details>' : ''}`;
    const linkControl = $('#sshLink');
    if (linkControl) linkControl.onclick = async () => {
      try { const plan = await request('/ssh/config/plan', {action:'include'}); await applyPlan(plan); }
      catch (error) { showError(error); }
    };
    $('#sshPanel').querySelectorAll('[data-ssh="config-file"]').forEach(control => { control.onclick = () => editConfig(control.dataset.file).catch(showError); });
    $('#sshPanel').querySelectorAll('[data-ssh="restore"]').forEach(control => { control.onclick = async () => {
      const backup = data.backups.find(item => item.id === control.dataset.backup);
      const file = data.files.find(item => item.relative === backup.file);
      await actionDialog('恢复配置备份', `将 ${backup.file} 恢复为 ${new Date(backup.created * 1000).toLocaleString()} 的版本。当前版本将另存备份。`, async () => {
        await request('/ssh/backups/restore', {backup:backup.id, revision:file?.revision, confirm:backup.file});
        submitting = false; dialog.close();
        await reload();
      });
    }; });
  }

  async function editConfig(fileId) {
    const result = await request('/ssh/config/read', {file:fileId});
    if (!await open(result.name + (result.editable ? ' · 高级编辑' : ''), form(`<p class="mono muted">${esc(result.path)}</p><textarea name="text" class="ssh-config-editor" aria-label="SSH 配置内容" spellcheck="false" ${result.editable ? '' : 'readonly'}>${esc(result.text)}</textarea>`, result.editable ? '预览差异' : '关闭'))) return;
    attachForm(async values => {
      if (!result.editable) { submitting = false; dialog.close(); return; }
      const plan = await request('/ssh/config/plan', {file:fileId, text:values.text, revision:result.revision});
      dirty = false;
      submitting = false;
      await applyPlan(plan);
    }, result.editable);
  }

  async function applyPlan(plan) {
    if (!plan.diff) { notify('配置没有变化'); return; }
    await actionDialog('确认配置修改', `修改 ${plan.file}。保存前会备份当前版本，并检查外部修改冲突。`, async () => {
      await request('/ssh/config/apply', {plan:plan.plan, confirm:plan.file});
      submitting = false; dialog.close();
      notify('SSH 配置已保存');
      await reload();
    }, `<pre class="ssh-diff">${esc(plan.diff)}</pre>`);
  }

  async function canLeave() {
    if (dialog?.open) return leaveDialog();
    return true;
  }

  function reset() {
    if (dialog?.open) { dirty = false; submitting = false; dialog.close(); }
    submitting = false;
    dialogEpoch++;
    current = () => false;
    renderEpoch++;
    overview = null;
  }

  return {render, canLeave, reset, isDirty: () => dirty};
})();
