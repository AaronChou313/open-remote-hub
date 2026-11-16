'use strict';
window.RemoteHubModules = (() => {
  const labels = {disabled:'未启用', missing_dependency:'缺少依赖', ready:'可用', error:'不可用'};
  async function render(current) {
    const result = await api('/modules');
    if (!current()) return;
    $('#content').innerHTML = '<div class="module-list">' + result.modules.map(module => `
      <section class="module-row">
        <div class="module-summary"><h2>${esc(module.name)}</h2><span class="badge">${labels[module.state]}</span></div>
        <p class="muted">${esc(module.dependency.detail)}</p>
        ${module.state !== 'ready' && module.guide.text ? `<p>${esc(module.guide.text)}</p>` : ''}
        ${module.state !== 'ready' && module.guide.command ? `<code class="module-command">${esc(module.guide.command)}</code>` : ''}
        <div class="toolbar">
          ${module.supported ? `<button data-module="${module.id}" data-operation="${module.enabled ? 'disable' : 'enable'}" ${module.enabled ? '' : 'class="primary"'}>${module.enabled ? '停用' : '启用'}</button>` : ''}
          ${module.state === 'ready' && document.querySelector('[data-view="' + module.entry + '"]') ? `<button data-module-entry="${module.entry}">打开</button>` : ''}
          ${module.guide.url && module.state !== 'ready' ? `<a class="button" href="${esc(module.guide.url)}" target="_blank" rel="noopener">安装说明</a>` : ''}
          ${module.enabled && module.state !== 'ready' ? '<button data-module-check>重新检测</button>' : ''}
        </div>
      </section>`).join('') + '</div>';
    document.querySelectorAll('[data-module]').forEach(button => button.onclick = () => withBusy(button, 'module:' + button.dataset.module, '处理中…', async () => {
      try {
        await api('/modules/' + button.dataset.module + '/' + button.dataset.operation, {});
        caps = await api('/capabilities');
        window.ORH_CAPS = caps;
        await render(current);
      } catch (error) { showError(error); }
    }));
    document.querySelectorAll('[data-module-entry]').forEach(button => button.onclick = () => switchView(button.dataset.moduleEntry));
    document.querySelectorAll('[data-module-check]').forEach(button => button.onclick = async () => { caps = await api('/capabilities'); window.ORH_CAPS = caps; await render(current); });
  }
  return {render};
})();
