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

  const encode = encodeURIComponent;
  const button = (action, label, attributes = '') => `<button type="button" data-ssh="${action}" ${attributes}>${label}</button>`;
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
    dialog.innerHTML = `<div class="detail-dialog-bar"><h2 id="sshDialogTitle">${esc(title)}</h2>${button('close', '关闭')}</div>${errorBox}<div class="ssh-dialog-body">${content}</div>`;
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

  async function privileged(title, impact, operation, target, work, content = '') {
    const epoch = await open(title, form(`<p>${esc(impact)}</p>${content}${field('password', '管理员登录密码', '', 'type="password" autocomplete="current-password" required maxlength="256"')}`, title));
    if (!epoch) return;
    attachForm(async (values, targetForm) => {
      const response = await request('/ssh/reauth', { operation, target, password: values.password });
      targetForm.elements.password.value = '';
      values.password = '';
      if (epoch !== dialogEpoch || !current()) return;
      await work(response.grant, values);
    }, false);
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
    $('#content').innerHTML = `<section class="ssh-center"><div class="ssh-tabs" role="tablist" aria-label="SSH 管理">${[
      ['connections', '连接管理'], ['keys', '密钥管理'], ['config', 'SSH 配置']
    ].map(([key, label]) => `<button type="button" role="tab" id="ssh-tab-${key}" aria-selected="${tab === key}" tabindex="${tab === key ? 0 : -1}" aria-controls="sshPanel" data-tab="${key}">${label}</button>`).join('')}</div><div id="sshPanel" role="tabpanel" aria-labelledby="ssh-tab-${tab}" tabindex="0"></div></section>`;
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
    $('#sshPanel').innerHTML = `${!overview.linked && overview.connections.some(row => row.managed) ? '<div class="ssh-attention"><p>受管连接尚未接入原生 Config</p><button id="sshIncludePreview">预览并接入</button></div>' : ''}<div class="ssh-toolbar"><input id="sshSearch" type="search" aria-label="搜索 SSH 连接" placeholder="搜索别名、地址或分组" value="${esc(query)}"><select id="sshGroup" aria-label="筛选分组"><option value="">所有分组</option>${groups.map(name => `<option value="${esc(name)}" ${group === name ? 'selected' : ''}>${esc(name)}</option>`).join('')}</select><button id="sshFavorites" aria-pressed="${favorites}">仅收藏</button><button id="sshNew" class="primary">＋ 新建连接</button></div><div id="sshConnections"></div>`;
    $('#sshSearch').oninput = event => { query = event.target.value; drawConnections(); };
    $('#sshGroup').onchange = event => { group = event.target.value; drawConnections(); };
    $('#sshFavorites').onclick = event => { favorites = !favorites; event.currentTarget.setAttribute('aria-pressed', favorites); drawConnections(); };
    $('#sshNew').onclick = () => connectionForm();
    const include = $('#sshIncludePreview');
    if (include) include.onclick = async () => {
      try { await applyPlan(await request('/ssh/config/plan', {action:'include'})); }
      catch (error) { showError(error); }
    };
    drawConnections();
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
      const live = overview.sessions.filter(session => session.host.toLowerCase() === row.alias.toLowerCase() && session.running);
      return `<article class="ssh-connection" data-host="${esc(row.alias)}"><div class="ssh-connection-title"><button class="ssh-star" data-ssh="favorite" aria-label="${favorite ? '取消收藏' : '收藏'} ${esc(row.alias)}" aria-pressed="${favorite}">${favorite ? '★' : '☆'}</button><h2>${esc(row.alias)}</h2><span class="badge">${row.managed ? '受管' : '原生配置'}</span></div><p class="mono ssh-address">${esc(row.hostname ? `${row.user ? row.user + '@' : ''}${row.hostname}:${row.port || 22}` : 'SSH Config')}</p><div class="ssh-connection-status">${category ? `<span>${esc(category)}</span>` : ''}${live.length ? `<span class="ssh-online">${live.length} 个活动连接</span>` : ''}${row.duplicate ? '<span class="danger-text">重复 Host</span>' : ''}</div><div class="ssh-row-actions"><button class="primary" data-ssh="connect">${live.length ? '进入终端 ↗' : '连接 ↗'}</button>${button('details', '管理')}</div></article>`;
    }).join('')}</div>` : empty(query || group || favorites ? '没有匹配的 SSH 连接' : '暂无连接，可新建连接或从 SSH Config 自动发现');
    $('#sshConnections').onclick = async event => {
      const control = event.target.closest('[data-ssh]');
      if (!control) return;
      const valid = current;
      const host = control.closest('[data-host]').dataset.host;
      const row = overview.connections.find(item => item.alias === host);
      try {
        if (control.dataset.ssh === 'connect') await connect(host, control);
        if (control.dataset.ssh === 'details') await details(row);
        if (control.dataset.ssh === 'favorite') {
          const favorite = row.metadata?.favorite ?? row.favorite ?? false;
          const result = await withBusy(control, 'ssh:favorite:' + host, '…', () => api('/ssh/connections/metadata', {alias: host, group: row.metadata?.group ?? row.group ?? '', favorite: !favorite}));
          if (!valid()) return;
          if (result?.revision) row.revision = result.revision;
          row.metadata = {...row.metadata, favorite: !favorite};
          drawConnections();
        }
      } catch (error) { if (valid()) showError(error); }
    };
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
    const epoch = await open(row ? '编辑 ' + row.alias : '新建 SSH 连接', '<p>读取密钥…</p>');
    if (!epoch) return;
    const data = await request('/ssh/keys');
    if (epoch !== dialogEpoch) return;
    dialog.querySelector('.ssh-dialog-body').innerHTML = form(`<div class="ssh-form-grid">${field('alias', '连接别名', row?.alias, 'required maxlength="80" pattern="[A-Za-z0-9][A-Za-z0-9_.-]*"')}${field('group', '分组', row?.metadata?.group ?? row?.group)}${field('hostname', '主机地址', row?.hostname, 'required maxlength="253"')}${field('port', '端口', row?.port || '22', 'type="number" min="1" max="65535" required')}${field('user', '用户名', row?.user, 'maxlength="80"')}${field('proxyjump', '跳板 ProxyJump', row?.proxyjump, 'placeholder="可选，例如 jump-host"')}<label>身份密钥<select name="identityfile"><option value="">使用原生默认设置</option>${data.keys.filter(key => key.private).map(key => {
      const path = overview.directory + '/' + key.name;
      return `<option value="${esc(path)}" ${row?.identityfile === path ? 'selected' : ''}>${esc(key.name)}</option>`;
    }).join('')}</select></label>${field('identityagent', 'SSH Agent', row?.identityagent, 'placeholder="SSH_AUTH_SOCK、none 或 Socket 绝对路径"')}<label>转发 SSH Agent<select name="forwardagent"><option value="">原生默认</option><option value="no" ${row?.forwardagent === 'no' ? 'selected' : ''}>关闭</option><option value="yes" ${row?.forwardagent === 'yes' ? 'selected' : ''}>开启</option></select></label><label>仅指定密钥<select name="identitiesonly"><option value="">原生默认</option><option value="yes" ${row?.identitiesonly === 'yes' ? 'selected' : ''}>是</option><option value="no" ${row?.identitiesonly === 'no' ? 'selected' : ''}>否</option></select></label></div>`, '保存连接');
    attachForm(async values => {
      await request('/ssh/connections/save', {...values, favorite: row?.favorite || false,
        original_alias: row?.alias, connection_revision: row?.revision, managed_revision: overview.managed_revision});
      dirty = false;
      submitting = false; dialog.close();
      notify('SSH 连接已保存');
      await reload();
    });
  }

  async function details(row) {
    const epoch = await open(row.alias, `<div class="ssh-row-actions">${button('edit', row.managed ? '编辑连接' : '编辑原生配置')}${button('new', '新建独立终端 ↗')}${button('diagnose', '连接诊断')}${button('fingerprint', '主机指纹')}${button('deploy', '部署公钥')}${button('organize', '设置分组')}${row.managed ? button('delete', '删除连接', 'class="danger"') : ''}</div><h3>生效配置</h3><div id="sshEffective">读取中…</div><h3>终端会话</h3><div id="sshTerminalList"></div>`);
    if (!epoch) return;
    const sessions = overview.sessions.filter(session => session.host.toLowerCase() === row.alias.toLowerCase());
    dialog.querySelector('#sshTerminalList').innerHTML = sessions.length ? sessions.map(session => `<div class="ssh-session-row"><span class="mono">${esc(session.session)}</span><span>${session.running ? '运行中' : session.state === 'completed' ? '已退出' : '已断开'}</span>${session.live_session ? `<a class="button" target="_blank" rel="noopener" href="/terminal/${encode(session.session)}">查看终端 ↗</a>` : ''}</div>`).join('') : '<p class="muted">尚无 SSH 终端</p>';
    dialog.querySelectorAll('[data-ssh]').forEach(control => {
      const action = control.dataset.ssh;
      if (action === 'close') return;
      control.onclick = async () => {
        try {
          if (action === 'edit') {
            if (row.managed) await connectionForm(row);
            else await editConfig(row.sources[0].file);
          }
          if (action === 'new') await connect(row.alias, control, true);
          if (action === 'diagnose') await diagnose(row.alias);
          if (action === 'fingerprint') await fingerprints(row.alias);
          if (action === 'deploy') await deploy(row.alias);
          if (action === 'organize') await organize(row);
          if (action === 'delete' && await confirmAction('删除连接 ' + row.alias + '？', '移除受管 SSH 配置。已运行的 SSH 终端会继续运行。')) {
            await request('/ssh/connections/delete', {alias: row.alias, confirm: row.alias, connection_revision: row.revision, managed_revision: overview.managed_revision});
            submitting = false; dialog.close();
            await reload();
          }
        } catch (error) { showDialogError(error); }
      };
    });
    try {
      const result = await request(`/ssh/connections/${encode(row.alias)}/effective`);
      if (epoch !== dialogEpoch) return;
      dialog.querySelector('#sshEffective').innerHTML = `<dl class="ssh-definition">${Object.entries(result).map(([key, value]) => `<dt>${esc(key)}</dt><dd class="mono">${esc(Array.isArray(value) ? value.join('\n') : value)}</dd>`).join('')}</dl>`;
    } catch (error) {
      if (epoch === dialogEpoch) dialog.querySelector('#sshEffective').textContent = error.message;
    }
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
      await privileged('移除主机指纹', `移除 ${result.label} 的已知指纹。下次连接需要重新核验身份。`, 'host-remove', host, async grant => {
        await request(`/ssh/hosts/${encode(host)}/remove`, {confirm:host, revision:result.revision, grant});
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
      if (result.known.length) {
        submitting = false;
        await privileged('更新主机指纹', `更新 ${result.label} 的信任记录。请先通过独立渠道核验新指纹。`, 'host-update', host, async grant => {
          await request('/ssh/hosts/trust', {...payload, grant});
          submitting = false;
          notify('主机指纹已更新');
          await fingerprintsView();
        }, `<pre>${esc(fingerprints.join('\n'))}</pre>`);
      } else {
        await request('/ssh/hosts/trust', payload);
        dirty = false;
        submitting = false;
        notify('主机指纹已保存');
        await fingerprintsView();
      }
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
    $('#sshPanel').innerHTML = `<div class="ssh-toolbar"><span class="muted">${data.keys.length} 个本地密钥</span><div class="ssh-row-actions"><button id="sshImport">导入密钥</button><button class="primary" id="sshGenerate">＋ 生成 ED25519</button></div></div><div class="ssh-key-list">${data.keys.length ? data.keys.map((key, index) => `<article class="ssh-key-row"><div><h2>${esc(key.name)}</h2><p class="muted">${key.unavailable ? '文件权限或格式不可读取' : `${esc(key.type || '私钥')} · ${key.private ? key.encrypted ? '口令保护' : '无口令' : '仅公钥'}`}</p>${key.fingerprint ? `<code>${esc(key.fingerprint)}</code>` : ''}</div>${key.unavailable ? '' : button('key', '管理', `data-index="${index}"`)}</article>`).join('') : empty('暂无 SSH 密钥')}</div><h3>密钥备份</h3><div>${data.backups.length ? data.backups.slice().reverse().map(backup => `<div class="ssh-config-file"><span>${esc(backup.file)}<small class="muted">${new Date(backup.created * 1000).toLocaleString()}</small></span>${button('key-restore', '恢复', `data-backup="${backup.id}"`)}</div>`).join('') : '<p class="muted">暂无密钥备份</p>'}</div>`;
    $('#sshGenerate').onclick = () => generate();
    $('#sshImport').onclick = () => importKey();
    $('#sshPanel').querySelectorAll('[data-ssh="key-restore"]').forEach(control => {
      control.onclick = () => {
        const backup = data.backups.find(item => item.id === control.dataset.backup);
        privileged('恢复密钥备份', `恢复 ${backup.file} 的选定备份。当前文件将另存备份。`, 'backup-restore', backup.file, async grant => {
          await request('/ssh/backups/restore', {grant, backup:backup.id, revision:data.revisions[backup.file], confirm:backup.file});
          submitting = false; dialog.close();
          await reload();
        }).catch(showError);
      };
    });
    $('#sshPanel').querySelectorAll('[data-ssh="key"]').forEach(control => { control.onclick = () => keyDetails(data.keys[Number(control.dataset.index)]); });
  }

  async function generate() {
    if (!await open('生成 ED25519 密钥', form(`${field('name', '密钥名称', '', 'required pattern="[A-Za-z0-9][A-Za-z0-9_.-]*" maxlength="96"')}${field('comment', '备注', '', 'maxlength="200"')}${field('passphrase', '密钥口令（可选）', '', 'type="password" autocomplete="new-password"')}${field('again', '再次输入密钥口令', '', 'type="password" autocomplete="new-password"')}`, '生成密钥'))) return;
    attachForm(async values => {
      if (values.passphrase !== values.again) throw Error('两次口令不一致');
      await request('/ssh/keys/generate', values);
      dirty = false;
      submitting = false; dialog.close();
      notify('密钥已生成');
      await reload();
    });
  }

  async function importKey() {
    if (!await open('导入 SSH 密钥', form(`${field('name', '保存名称', '', 'required maxlength="96"')}<label>私钥文件（可选）<input type="file" name="privateFile"></label><label>公钥文件（可选）<input type="file" name="publicFile" accept=".pub,text/plain"></label>${field('passphrase', '私钥口令（如已加密）', '', 'type="password" autocomplete="off"')}${field('password', '管理员登录密码', '', 'type="password" autocomplete="current-password" required')}`, '导入密钥'))) return;
    attachForm(async (values, target) => {
      const privateFile = target.elements.privateFile.files[0];
      const publicFile = target.elements.publicFile.files[0];
      if (!privateFile && !publicFile) throw Error('请选择私钥或公钥文件');
      if ((privateFile?.size || 0) > 65536 || (publicFile?.size || 0) > 16384) throw Error('密钥文件过大');
      const auth = await request('/ssh/reauth', {operation: 'key-import', target: values.name, password: values.password});
      target.elements.password.value = '';
      await request('/ssh/keys/import', {name: values.name, passphrase: values.passphrase, private: privateFile ? await privateFile.text() : '', public: publicFile ? await publicFile.text() : '', grant: auth.grant});
      dirty = false;
      submitting = false; dialog.close();
      notify('密钥已导入');
      await reload();
    });
  }

  async function copyPublic(text) {
    if (window.isSecureContext && navigator.clipboard?.writeText) {
      try { await navigator.clipboard.writeText(text); return; }
      catch { /* Continue with the user-initiated HTTP-compatible copy path. */ }
    }
    const input = dialog.querySelector('.ssh-public');
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

  async function keyDetails(key) {
    const epoch = await open(key.name, `${key.public ? `<textarea class="ssh-public" readonly aria-label="SSH 公钥">${esc(key.public)}</textarea><div class="ssh-row-actions">${button('copy', '复制公钥')}<a class="button" href="/api/ssh/keys/${encode(key.name)}/public" download>下载公钥</a></div>` : '<p class="muted">尚无公钥文件。</p>' + button('derive', '生成匹配公钥')}<h3>关联连接</h3><div id="sshKeyReferences">读取中…</div><div class="ssh-row-actions">${key.private ? button('passphrase', '修改密钥口令') + button('export', '导出私钥') : ''}${button('delete', '删除密钥', 'class="danger"')}</div>`);
    if (!epoch) return;
    dialog.querySelectorAll('[data-ssh]').forEach(control => {
      const action = control.dataset.ssh;
      if (action === 'close') return;
      control.onclick = async () => {
        try {
          if (action === 'derive') {
            if (!await open('生成匹配公钥', form(field('passphrase', '私钥口令（如已加密）', '', 'type="password" autocomplete="off"'), '生成公钥'))) return;
            attachForm(async values => {
              await request(`/ssh/keys/${encode(key.name)}/recover-public`, values);
              submitting = false; dialog.close();
              await reload();
            });
          }
          if (action === 'copy') { await copyPublic(key.public); notify('公钥已复制'); }
          if (action === 'export') await privileged('导出私钥', `将 ${key.name} 下载到当前设备，请妥善保存。`, 'key-export', key.name, async grant => {
            const exportEpoch = dialogEpoch;
            const response = await fetch(`/api/ssh/keys/${encode(key.name)}/export`, {method: 'POST', headers: {'Content-Type':'application/json', 'X-ORH-Request':'1'}, body: JSON.stringify({grant}), signal: AbortSignal.timeout(10000)});
            if (!response.ok) throw Error((await response.json()).detail || '私钥导出失败');
            const blob = await response.blob();
            if (exportEpoch !== dialogEpoch || !current()) return;
            const url = URL.createObjectURL(blob);
            const anchor = document.createElement('a');
            anchor.href = url;
            anchor.download = key.name;
            anchor.click();
            setTimeout(() => URL.revokeObjectURL(url), 1000);
            submitting = false; dialog.close();
          });
          if (action === 'passphrase') await privileged('修改密钥口令', `更新 ${key.name} 的加密口令。原文件将保留私有备份。`, 'key-passphrase', key.name, async (grant, values) => {
            if (values.passphrase !== values.again) throw Error('两次新口令不一致');
            await request(`/ssh/keys/${encode(key.name)}/passphrase`, {...values, password: undefined, grant, revision:key.revision});
            submitting = false; dialog.close();
            await reload();
          }, `${key.encrypted !== false ? field('old_passphrase', '当前密钥口令', '', 'type="password" autocomplete="off"') : ''}${field('passphrase', '新密钥口令（留空则移除）', '', 'type="password" autocomplete="new-password"')}${field('again', '再次输入新口令', '', 'type="password" autocomplete="new-password"')}`);
          if (action === 'delete') await privileged('删除密钥', `删除 ${key.name} 及其公钥。被连接引用的密钥会被阻止删除，文件保留私有备份。`, 'key-delete', key.name, async grant => {
            await request(`/ssh/keys/${encode(key.name)}/delete`, {grant, confirm:key.name, revision:key.revision, public_revision:key.public_revision});
            submitting = false; dialog.close();
            await reload();
          });
        } catch (error) { showDialogError(error); }
      };
    });
    try {
      const references = await request(`/ssh/keys/${encode(key.name)}/references`);
      if (epoch !== dialogEpoch) return;
      dialog.querySelector('#sshKeyReferences').textContent = references.connections.length || references.rules?.length ? [...references.connections, ...(references.rules || [])].join('、') : references.unresolved.length ? '部分连接配置需要核验，暂时无法完成引用检查' : '无关联连接';
    } catch (error) { if (epoch === dialogEpoch) showDialogError(error); }
  }

  async function renderConfig(version) {
    const data = await request('/ssh/config');
    if (!current() || version !== renderEpoch || tab !== 'config') return;
    $('#sshPanel').innerHTML = `<div class="ssh-config-header"><div><h2>原生 SSH Config</h2><p class="mono muted">${esc(overview.directory)}</p></div>${!data.include.linked ? '<button class="primary" id="sshLink">接入原生 Config</button>' : '<span class="ssh-online">受管 Include 已接入</span>'}</div>${data.requires_trust ? '<div class="ssh-attention"><p>配置包含可执行命令规则，使用前需核验当前版本。</p><button id="sshTrustConfig">核验并授权命令规则</button></div>' : ''}<div class="ssh-config-files">${data.files.map(file => `<div class="ssh-config-file"><div><strong>${esc(file.name)}</strong><p class="mono muted">${esc(file.path)}</p></div>${button('config-file', file.editable ? '查看 / 高级编辑' : '查看', `data-file="${file.id}"`)}</div>`).join('') || empty('尚无 SSH Config')}</div>${data.rules.length ? `<details class="ssh-rule-list"><summary>Host 模式规则 · ${data.rules.length}</summary><pre>${esc(data.rules.map(rule => rule.pattern).join('\n'))}</pre></details>` : ''}${data.warnings.map(warning => `<p class="danger-text">${esc(warning)}</p>`).join('')}<h3>配置备份</h3><div class="ssh-backups">${data.backups.slice().reverse().map(backup => `<div class="ssh-config-file"><span>${esc(backup.file)}<small class="muted">${new Date(backup.created * 1000).toLocaleString()}</small></span>${button('restore', '恢复', `data-backup="${backup.id}"`)}</div>`).join('') || '<p class="muted">暂无配置备份</p>'}</div>`;
    const linkControl = $('#sshLink');
    if (linkControl) linkControl.onclick = async () => {
      try { const plan = await request('/ssh/config/plan', {action:'include'}); await applyPlan(plan); }
      catch (error) { showError(error); }
    };
    const trustControl = $('#sshTrustConfig');
    if (trustControl) trustControl.onclick = () => privileged('授权原生命令规则', `授权当前配置中的 Match exec、ProxyCommand 等指令以宿主机用户权限运行。请先查看并核验配置内容。`, 'config-trust', data.signature, async grant => {
      await request('/ssh/config/trust', {grant, signature:data.signature, confirm:data.signature});
      submitting = false; dialog.close();
      await reload();
    });
    $('#sshPanel').querySelectorAll('[data-ssh="config-file"]').forEach(control => { control.onclick = () => editConfig(control.dataset.file).catch(showError); });
    $('#sshPanel').querySelectorAll('[data-ssh="restore"]').forEach(control => { control.onclick = async () => {
      const backup = data.backups.find(item => item.id === control.dataset.backup);
      const file = data.files.find(item => item.relative === backup.file);
      await privileged('恢复配置备份', `将 ${backup.file} 恢复为 ${new Date(backup.created * 1000).toLocaleString()} 的版本。当前版本将另存备份。`, 'backup-restore', backup.file, async grant => {
        await request('/ssh/backups/restore', {grant, backup:backup.id, revision:file?.revision, confirm:backup.file});
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
    await privileged('确认配置修改', `修改 ${plan.file}。保存前会备份当前版本，并检查外部修改冲突。`, 'config-apply', plan.file, async grant => {
      await request('/ssh/config/apply', {plan:plan.plan, grant, confirm:plan.file});
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
