/* Directory-backed notebooks, with the console's neutral surfaces and indigo controls.
 * Browse libraries, open a note, then read or edit in place. The file tree remains
 * alongside the document on desktop and folds above it on phones. */
'use strict';
window.RemoteHubKnowledge = (() => {
  let current = () => false;
  let library = null;
  let entries = [];
  let note = null;
  let draft = '';
  let mode = 'read';
  let dirty = false;
  let saving = false;
  let generation = 0;
  let search = '';
  let dialog;
  let formBusy = false;
  let picker;
  let pickerRequest = 0;
  const expandedFolders = new Set();
  const encode = encodeURIComponent;
  const admin = () => me.role === 'admin';
  const basename = path => path.split('/').at(-1);
  const parent = path => path.split('/').slice(0, -1).join('/');
  const endpoint = (suffix, path) => `/knowledge/${encode(library.id)}/${suffix}` + (path === undefined ? '' : '?' + new URLSearchParams({path}));
  const action = (id, text, glyph, attributes = '') => `<button type="button" ${id ? `id="${id}"` : ''} ${attributes}>${icon(glyph)}${text}</button>`;

  async function canLeave() {
    if (saving || formBusy) { notify('正在保存，请稍候'); return false; }
    if (!dirty) return true;
    if (!await confirmAction('放弃未保存的笔记修改？', note?.path || '')) return false;
    dirty = false;
    draft = note?.text || '';
    if (note && $('#kbNoteBody')) {
      drawNoteBody();
      $('#kbSave').disabled = true;
      $('#kbNoteState').textContent = '已恢复保存的内容';
    }
    return true;
  }

  function reset() {
    generation++;
    dirty = false;
    note = null;
    draft = '';
    library = null;
    if (dialog?.open) dialog.close();
    if (picker?.open) picker.close();
    pickerRequest++;
    expandedFolders.clear();
  }

  function bind(selector, work) {
    const control = $(selector);
    if (control) control.onclick = async event => {
      try { await work(event); }
      catch (error) { if (current()) showError(error); }
    };
  }

  function form(title, body, submit, work) {
    if (!dialog) {
      dialog = document.createElement('dialog');
      dialog.className = 'kb-dialog';
      dialog.setAttribute('aria-labelledby', 'kbDialogTitle');
      document.body.append(dialog);
      dialog.addEventListener('cancel', event => { if (formBusy) event.preventDefault(); });
    }
    dialog.innerHTML = `<form><div class="detail-dialog-bar"><h2 id="kbDialogTitle">${esc(title)}</h2><button type="button" data-close>${icon('close')}关闭</button></div>${body}<p class="kb-form-error danger-text" role="alert" hidden></p><div class="dialog-actions"><button type="submit" class="primary">${submit}</button></div></form>`;
    const target = dialog.querySelector('form');
    dialog.querySelector('[data-close]').onclick = () => { if (!formBusy) dialog.close(); };
    target.onsubmit = async event => {
      event.preventDefault();
      if (formBusy) return;
      const values = Object.fromEntries(new FormData(target));
      const controls = [...target.querySelectorAll('input, button')];
      formBusy = true;
      controls.forEach(control => { control.disabled = true; });
      try {
        await work(values);
        dialog.close();
      } catch (error) {
        const output = dialog.querySelector('.kb-form-error');
        output.textContent = error.message;
        output.hidden = false;
      } finally {
        formBusy = false;
        controls.forEach(control => { control.disabled = false; });
      }
    };
    dialog.showModal();
    target.querySelector('input')?.focus();
  }

  async function render(check, checkChanges = true) {
    current = check;
    if (checkChanges && !await canLeave()) return;
    const token = ++generation;
    if (library) {
      await openLibrary(library.id, token);
      return;
    }
    const data = await api('/knowledge');
    if (!check() || token !== generation) return;
    $('#content').innerHTML = `<section class="kb-home"><div class="kb-toolbar"><label class="kb-search">${icon('search')}<input id="kbLibrarySearch" type="search" placeholder="搜索知识库" aria-label="搜索知识库"></label>${admin() ? `<div class="kb-actions">${action('kbAttach', '添加目录', 'folder')}${action('kbCreate', '新建知识库', 'plus', 'class="primary"')}</div>` : ''}</div><div id="kbLibraries"></div></section>`;
    function draw(query = '') {
      const rows = data.libraries.filter(row => (row.name + ' ' + row.directory).toLowerCase().includes(query.toLowerCase()));
      $('#kbLibraries').innerHTML = rows.length ? `<div class="kb-library-grid">${rows.map(row => `<article class="kb-library" data-library="${esc(row.id)}"><div class="kb-library-heading">${icon('knowledge')}<h2>${esc(row.name)}</h2></div><p class="kb-library-path mono">${esc(row.directory)}</p>${row.available ? '' : `<p class="danger-text">${esc(row.error)}</p>`}<div class="kb-library-actions">${action('', '打开', 'knowledge', `data-action="open" class="primary" ${row.available ? '' : 'disabled'}`)}${admin() ? `${action('', '编辑', 'rename', 'data-action="edit"')}${action('', '移除知识库', 'link', 'data-action="remove" class="danger kb-remove" title="移除目录关联，保留磁盘文件"')}${row.available && row.path ? action('', '删除目录', 'delete', 'data-action="trash" class="danger kb-trash" title="将目录及全部文件移入回收目录"') : ''}` : ''}</div></article>`).join('')}</div>` : empty(query ? '没有匹配的知识库' : '添加主机上的笔记目录，或创建一个新的知识库。');
      $('#kbLibraries').querySelectorAll('[data-action]').forEach(control => {
        control.onclick = async () => {
          const row = rows.find(item => item.id === control.closest('[data-library]').dataset.library);
          try {
            if (control.dataset.action === 'open') { search = ''; note = null; mode = 'read'; await openLibrary(row.id); }
            if (control.dataset.action === 'edit') libraryForm(false, row);
            if (control.dataset.action === 'remove') {
              await withBusy(control, 'kb:remove:' + row.id, '移除中…', () => api('/knowledge/' + row.id, {action:'remove', revision:row.revision}));
              notify('已移除目录关联');
              await render(check);
            }
            if (control.dataset.action === 'trash' && await confirmAction('删除目录 ' + row.name + '？', `将整个目录及其中全部文件移入回收目录。\n${row.directory}`)) {
              await withBusy(control, 'kb:trash:' + row.id, '删除中…', () => api('/knowledge/' + row.id, {action:'trash', revision:row.revision, confirm:row.id}));
              notify('知识库目录已移入回收目录');
              await render(check);
            }
          } catch (error) { if (check()) showError(error); }
        };
      });
    }
    draw();
    $('#kbLibrarySearch').oninput = event => draw(event.target.value);
    bind('#kbAttach', () => libraryForm(false));
    bind('#kbCreate', () => libraryForm(true));
  }

  function libraryForm(create, row) {
    const title = row ? '编辑知识库' : create ? '新建知识库' : '添加目录';
    form(title, `<label>名称<input name="name" value="${esc(row?.name || '')}" maxlength="100" placeholder="留空使用目录名称"></label><label for="kbDirectory">主机目录</label><div class="kb-directory-input"><input id="kbDirectory" name="directory" value="${esc(row?.directory || '')}" required placeholder="${create ? '~/Knowledge/我的知识库' : '~/Documents/笔记'}" autocomplete="off"><button type="button" id="kbBrowseDirectory">${icon('folder')}浏览</button></div>`, row ? '保存' : create ? '创建' : '添加', async values => {
      await api(row ? '/knowledge/' + row.id : '/knowledge', row ? {...values, revision:row.revision} : {...values, create});
      notify(row ? '知识库已更新' : '知识库已添加');
      await render(current, false);
    });
    dialog.querySelector('#kbBrowseDirectory').onclick = () => chooseDirectory(dialog.querySelector('[name="directory"]'));
  }

  async function chooseDirectory(input) {
    if (!picker) {
      picker = document.createElement('dialog');
      picker.className = 'kb-picker';
      picker.setAttribute('aria-labelledby', 'kbPickerTitle');
      document.body.append(picker);
      picker.addEventListener('close', () => { pickerRequest++; });
    }
    picker.innerHTML = `<div class="detail-dialog-bar"><h2 id="kbPickerTitle">选择知识库目录</h2><button id="kbPickerClose" type="button">${icon('close')}关闭</button></div>
      <div class="kb-picker-location"><label class="sr-only" for="kbPickerPath">目录路径</label><input id="kbPickerPath" autocomplete="off"><button id="kbPickerGo" type="button">前往</button></div>
      <div class="kb-picker-navigation"><button id="kbPickerUp" type="button" disabled>${icon('up')}上一级</button><button id="kbPickerHome" type="button" disabled>${icon('folder')}主目录</button><label class="sr-only" for="kbPickerRoot">文件系统</label><select id="kbPickerRoot" aria-label="文件系统"></select><button id="kbPickerNew" type="button" disabled>${icon('mkdir')}新建文件夹</button></div>
      <div class="kb-picker-create" hidden><input id="kbPickerFolderName" aria-label="新文件夹名称" placeholder="新文件夹名称"><button id="kbPickerMkdir" type="button">创建</button></div>
      <p id="kbPickerStatus" class="muted" role="status">正在读取目录…</p><div id="kbPickerDirectories"></div><button id="kbPickerMore" type="button" hidden>加载更多目录</button>
      <div class="dialog-actions"><button id="kbPickerSelect" type="button" class="primary" disabled>选择此目录</button></div>`;
    picker.showModal();
    const control = selector => picker.querySelector(selector);
    let selected = null;
    let homeDirectory;
    const handle = work => async () => {
      try { await work(); }
      catch (error) { if (picker.open) control('#kbPickerStatus').textContent = error.message; }
    };
    async function load(directory, offset = 0) {
      const token = ++pickerRequest;
      control('#kbPickerStatus').textContent = '正在读取目录…';
      control('#kbPickerSelect').disabled = true;
      const data = await api('/knowledge/directories?' + new URLSearchParams({directory, offset}));
      if (!picker.open || token !== pickerRequest) return;
      const folders = offset ? [...selected.directories, ...data.directories] : data.directories;
      selected = {...data, directories:folders};
      control('#kbPickerPath').value = data.directory;
      control('#kbPickerUp').disabled = !data.parent;
      homeDirectory = data.home;
      control('#kbPickerHome').disabled = !homeDirectory;
      control('#kbPickerNew').disabled = false;
      control('#kbPickerSelect').disabled = false;
      control('#kbPickerRoot').innerHTML = data.roots.map(root => `<option value="${esc(root.path)}" ${root.id === data.root ? 'selected' : ''}>${esc(root.path)}</option>`).join('');
      control('#kbPickerDirectories').innerHTML = folders.length ? folders.map((folder, index) => `<button type="button" data-directory="${index}">${icon('folder')}<span>${esc(folder.name)}</span>${icon('chevron')}</button>`).join('') : '<p class="muted kb-picker-empty">此目录没有子文件夹</p>';
      control('#kbPickerStatus').textContent = folders.length + ' 个文件夹';
      control('#kbPickerMore').hidden = data.next_offset === null;
      control('#kbPickerDirectories').querySelectorAll('[data-directory]').forEach(button => {
        button.onclick = handle(() => load(selected.directory.replace(/\/$/, '') + '/' + selected.directories[Number(button.dataset.directory)].name));
      });
    }
    control('#kbPickerClose').onclick = () => picker.close();
    control('#kbPickerGo').onclick = handle(() => load(control('#kbPickerPath').value));
    control('#kbPickerPath').onkeydown = event => { if (event.key === 'Enter') { event.preventDefault(); control('#kbPickerGo').click(); } };
    control('#kbPickerUp').onclick = handle(() => load(selected.parent));
    control('#kbPickerHome').onclick = handle(() => load(homeDirectory));
    control('#kbPickerRoot').onchange = handle(() => load(control('#kbPickerRoot').value));
    control('#kbPickerMore').onclick = handle(() => load(selected.directory, selected.next_offset));
    control('#kbPickerSelect').onclick = () => { input.value = selected.directory; picker.close(); input.focus(); };
    control('#kbPickerNew').onclick = () => { control('.kb-picker-create').hidden = !control('.kb-picker-create').hidden; control('#kbPickerFolderName').focus(); };
    control('#kbPickerMkdir').onclick = handle(async () => {
      if (!selected) return;
      const name = control('#kbPickerFolderName').value.trim();
      if (!name || name.includes('/') || name.includes('\\')) throw Error('请输入单个文件夹名称');
      await withBusy(control('#kbPickerMkdir'), 'kb:mkdir', '创建中…', () => api('/files/operation', {root:selected.root, path:[selected.path, name].filter(Boolean).join('/'), action:'mkdir'}));
      control('.kb-picker-create').hidden = true;
      control('#kbPickerFolderName').value = '';
      await load(selected.directory.replace(/\/$/, '') + '/' + name);
    });
    await handle(async () => {
      const config = await api('/files/roots');
      homeDirectory = config.default ? config.home : config.roots[0]?.path;
      control('#kbPickerHome').disabled = !homeDirectory;
      control('#kbPickerRoot').innerHTML = config.roots.map(root => `<option value="${esc(root.path)}">${esc(root.path)}</option>`).join('');
      const initial = input.value || homeDirectory;
      if (!initial) throw Error('没有可访问的目录');
      await load(initial);
    })();
  }

  async function openLibrary(id, token = ++generation) {
    const owner = current;
    const data = await api(`/knowledge/${encode(id)}/tree`);
    if (!owner() || token !== generation) return;
    if (library?.id !== id) expandedFolders.clear();
    library = data;
    entries = data.entries;
    $('#content').innerHTML = `<section class="kb-workspace"><div class="kb-workspace-heading"><div>${action('kbBack', '知识库', 'folder', 'class="kb-back"')}<h2>${esc(data.name)}</h2><p class="mono muted">${esc(data.directory)}</p></div><div class="kb-actions">${admin() ? action('kbNewNote', '新建笔记', 'plus', 'class="primary"') : ''}${action('kbFiles', '文件管理', 'folder')}</div></div><div class="kb-layout"><details class="kb-browser" open><summary>笔记目录 <span>${data.count}</span>${icon('chevron')}</summary><label class="kb-search">${icon('search')}<input id="kbNoteSearch" type="search" placeholder="搜索笔记名称或路径" aria-label="搜索笔记名称或路径" value="${esc(search)}"></label><div id="kbTree"></div>${data.truncated ? '<p class="kb-tree-status muted">目录较大，已显示本次扫描的部分内容。</p>' : ''}${data.warnings.length ? `<p class="kb-tree-status muted">${data.warnings.length} 个目录无法读取</p>` : ''}</details><section class="kb-document" id="kbDocument">${empty('选择一篇笔记开始阅读')}</section></div></section>`;
    bind('#kbBack', async () => { if (!await canLeave()) return; library = null; note = null; await render(owner); });
    bind('#kbNewNote', newNote);
    bind('#kbFiles', async () => {
      if (!await canLeave()) return;
      RemoteHubWorkspace.state.root = library.root;
      RemoteHubWorkspace.state.path = library.path;
      RemoteHubWorkspace.state.selected = null;
      await switchView('files');
    });
    drawTree();
    $('#kbNoteSearch').oninput = event => { search = event.target.value; drawTree(); };
    if (note && entries.some(entry => entry.path === note.path && entry.kind === 'file')) await openNote(note.path, false, mode);
    else { note = null; dirty = false; }
  }

  function treeMarkup(rows, query = '') {
    rows = rows.filter(row => row.kind === 'directory' || row.kind === 'file' && /\.(md|markdown)$/i.test(row.name));
    const notes = rows.filter(row => row.kind === 'file' && row.path.toLowerCase().includes(query.toLowerCase()));
    const matches = new Set(notes.map(row => row.path));
    const folders = new Set();
    for (const row of notes) {
      let folder = parent(row.path);
      while (folder) { folders.add(folder); folder = parent(folder); }
    }
    const visible = rows.filter(row => row.kind === 'file' ? matches.has(row.path) : !query || folders.has(row.path));
    const children = new Map();
    for (const row of visible) {
      const key = parent(row.path);
      if (!children.has(key)) children.set(key, []);
      children.get(key).push(row);
    }
    function branch(path) {
      const values = (children.get(path) || []).sort((a, b) => (a.kind !== 'directory') - (b.kind !== 'directory') || a.name.localeCompare(b.name, 'zh-CN', {numeric:true}));
      return values.map(row => row.kind === 'directory' ? `<details class="kb-tree-folder" data-folder="${esc(row.path)}" ${query || expandedFolders.has(row.path) || note?.path.startsWith(row.path + '/') ? 'open' : ''}><summary><span class="kb-folder-chevron">${icon('chevron')}</span>${icon('folder')}<span>${esc(row.name)}</span></summary><div>${branch(row.path)}</div></details>` : `<button class="kb-note-link" data-note="${esc(row.path)}" aria-current="${note?.path === row.path ? 'page' : 'false'}">${icon('file')}<span>${esc(row.name.replace(/\.(md|markdown)$/i, ''))}</span></button>`).join('');
    }
    return notes.length || visible.some(row => row.kind === 'directory') ? branch('') : '<p class="kb-tree-status muted">没有匹配的笔记</p>';
  }

  function drawTree() {
    $('#kbTree').querySelectorAll('[data-folder]').forEach(folder => {
      if (folder.open) expandedFolders.add(folder.dataset.folder);
      else expandedFolders.delete(folder.dataset.folder);
    });
    $('#kbTree').innerHTML = treeMarkup(entries, search);
    $('#kbTree').onclick = async event => {
      const control = event.target.closest('[data-note]');
      if (!control) return;
      try { await openNote(control.dataset.note); }
      catch (error) { if (current()) showError(error); }
    };
  }

  async function openNote(path, checkChanges = true, nextMode = 'read') {
    if (checkChanges && !await canLeave()) return;
    const token = ++generation;
    const owner = current;
    const data = await api(endpoint('note', path));
    if (!owner() || token !== generation) return;
    note = data;
    draft = data.text;
    dirty = false;
    mode = nextMode;
    drawNote();
    drawTree();
    if (matchMedia('(max-width: 760px)').matches) $('.kb-browser').open = false;
    if (checkChanges) $('#kbDocument').scrollIntoView({block:'start'});
  }

  function drawNote() {
    $('#kbDocument').innerHTML = `<div class="kb-note-header"><div><h3>${esc(basename(note.path))}</h3><span class="kb-note-state muted" id="kbNoteState">${new Date(note.modified * 1000).toLocaleString()}</span></div><div class="kb-note-modes" role="group" aria-label="笔记显示方式"><button data-mode="read" aria-pressed="${mode === 'read'}">阅读</button>${admin() ? `<button data-mode="edit" aria-pressed="${mode === 'edit'}">${icon('rename')}编辑</button>` : ''}</div></div><div class="kb-note-toolbar">${admin() ? `${action('kbSave', '保存', 'save', `class="primary" ${dirty ? '' : 'disabled'}`)}${action('kbRename', '重命名', 'rename')}${action('kbDelete', '删除', 'delete', 'class="danger"')}` : ''}<a class="button" href="/api${endpoint('asset', note.path)}" download>${icon('download')}下载</a></div><div id="kbNoteBody"></div>`;
    drawNoteBody();
    document.querySelectorAll('[data-mode]').forEach(control => {
      control.onclick = () => {
        mode = control.dataset.mode;
        document.querySelectorAll('[data-mode]').forEach(button => button.setAttribute('aria-pressed', button.dataset.mode === mode));
        drawNoteBody();
      };
    });
    bind('#kbSave', save);
    bind('#kbRename', renameNote);
    bind('#kbDelete', deleteNote);
  }

  function relativePath(url, source) {
    const raw = url.split('#')[0].split('?')[0];
    if (/^[a-z][a-z0-9+.-]*:/i.test(raw) || raw.startsWith('//')) return null;
    let decoded;
    try { decoded = decodeURIComponent(raw); } catch { return null; }
    const chunks = decoded.startsWith('/') ? [] : parent(source).split('/').filter(Boolean);
    for (const part of decoded.split('/')) {
      if (!part || part === '.') continue;
      if (part === '..') { if (!chunks.length) return null; chunks.pop(); }
      else chunks.push(part);
    }
    return chunks.join('/');
  }

  function drawNoteBody() {
    const body = $('#kbNoteBody');
    if (mode === 'edit') {
      body.innerHTML = `<textarea id="kbEditor" class="kb-editor" aria-label="Markdown 笔记内容" spellcheck="false">${esc(draft)}</textarea>`;
      $('#kbEditor').oninput = event => {
        draft = event.target.value;
        dirty = draft !== note.text;
        $('#kbSave').disabled = !dirty || saving;
        $('#kbNoteState').textContent = dirty ? '未保存' : '已保存';
      };
      return;
    }
    body.innerHTML = '<article class="kb-markdown"></article>';
    const preview = body.querySelector('article');
    preview.innerHTML = DOMPurify.sanitize(marked.parse(draft.replace(/^\uFEFF/, ''), {gfm:true}), {USE_PROFILES:{html:true}, FORBID_TAGS:['form','style','iframe','object','embed'], FORBID_ATTR:['style'], SANITIZE_NAMED_PROPS:true});
    if (!draft.trim()) preview.innerHTML = '<p class="muted">这篇笔记还没有内容</p>';
    preview.querySelectorAll('input').forEach(input => { input.disabled = true; });
    preview.querySelectorAll('h1, h2, h3, h4, h5, h6').forEach(heading => { if (!heading.id) heading.id = heading.textContent.trim().toLowerCase().replace(/\s+/g, '-'); });
    preview.querySelectorAll('img').forEach(image => {
      const path = relativePath(image.getAttribute('src') || '', note.path);
      if (path) image.src = '/api' + endpoint('asset', path);
    });
    preview.querySelectorAll('a').forEach(link => {
      const href = link.getAttribute('href') || '';
      if (!href) return;
      if (href.startsWith('#')) {
        let anchor;
        try { anchor = decodeURIComponent(href.slice(1)); } catch { anchor = href.slice(1); }
        link.onclick = event => { event.preventDefault(); [...preview.querySelectorAll('[id]')].find(el => el.id === anchor || el.id === 'user-content-' + anchor)?.scrollIntoView({block:'start'}); };
        return;
      }
      const path = relativePath(href, note.path);
      if (path && entries.some(entry => entry.kind === 'directory' && entry.path === path)) {
        link.href = '#';
        link.onclick = event => { event.preventDefault(); showFolder(path); };
      } else if (path && /\.(md|markdown)$/i.test(path)) {
        link.href = '#';
        link.onclick = async event => { event.preventDefault(); try { await openNote(path); } catch (error) { showError(error); } };
      } else if (path) link.href = '/api' + endpoint('asset', path);
      else { link.target = '_blank'; link.rel = 'noopener noreferrer'; }
    });
  }

  function showFolder(path) {
    let folder = path;
    while (folder) { expandedFolders.add(folder); folder = parent(folder); }
    $('#kbTree').querySelectorAll('[data-folder]').forEach(row => { if (expandedFolders.has(row.dataset.folder)) row.open = true; });
    search = '';
    $('#kbNoteSearch').value = '';
    $('.kb-browser').open = true;
    drawTree();
    const target = [...$('#kbTree').querySelectorAll('[data-folder]')].find(row => row.dataset.folder === path);
    target?.querySelector('summary').focus();
    target?.scrollIntoView({block:'nearest'});
  }

  async function save() {
    if (!note || !dirty || saving) return;
    const selected = note;
    const submitted = draft;
    const owner = current;
    saving = true;
    try {
      const result = await withBusy($('#kbSave'), 'kb:save', '保存中…', () => api(endpoint('note'), {path:selected.path, text:submitted, revision:selected.revision}));
      if (!owner() || note !== selected) return;
      note.revision = result.revision;
      note.entry_revision = result.entry_revision || result.revision;
      note.text = submitted;
      note.modified = result.modified;
      dirty = draft !== submitted;
      $('#kbNoteState').textContent = dirty ? '仍有未保存修改' : '已保存';
      $('#kbSave').disabled = !dirty;
      notify('笔记已保存');
    } finally { saving = false; }
  }

  async function newNote() {
    if (!await canLeave()) return;
    const base = note ? parent(note.path) : '';
    form('新建笔记', `<label>笔记路径<input name="path" required value="${esc((base ? base + '/' : '') + '新笔记.md')}" placeholder="例如 研究/思路.md" autocomplete="off"></label>`, '创建并编辑', async values => {
      let path = values.path.trim();
      if (!/\.(md|markdown)$/i.test(path)) path += '.md';
      await api(endpoint('note'), {path, text:''});
      note = null;
      await openLibrary(library.id);
      await openNote(path, false, 'edit');
    });
  }

  async function renameNote() {
    if (!await canLeave()) return;
    form('重命名笔记', `<label>文件名<input name="name" required value="${esc(basename(note.path))}" autocomplete="off"></label>`, '重命名', async values => {
      let name = values.name.trim();
      if (!/\.(md|markdown)$/i.test(name)) name += '.md';
      const destination = [parent(note.path), name].filter(Boolean).join('/');
      await api(endpoint('operation'), {path:note.path, revision:note.entry_revision, action:'rename', destination});
      note = null;
      await openLibrary(library.id);
      await openNote(destination, false, mode);
    });
  }

  async function deleteNote() {
    if (saving || formBusy) { notify('正在保存，请稍候'); return; }
    if (!await confirmAction('删除笔记 ' + note.path + '？', '笔记将移入所在目录的回收目录。')) return;
    await withBusy($('#kbDelete'), 'kb:delete', '删除中…', () => api(endpoint('operation'), {path:note.path, revision:note.entry_revision, action:'delete', confirm:note.path}));
    dirty = false;
    note = null;
    await openLibrary(library.id);
    notify('笔记已移入回收目录');
  }

  document.addEventListener('keydown', event => {
    if (!current() || !note || mode !== 'edit' || !(event.ctrlKey || event.metaKey) || event.key.toLowerCase() !== 's') return;
    event.preventDefault();
    save().catch(showError);
  });
  window.addEventListener('beforeunload', event => { if (dirty) { event.preventDefault(); event.returnValue = ''; } });
  return {render, canLeave, reset, isDirty:() => dirty};
})();
