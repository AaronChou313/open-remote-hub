'use strict';
// SVG assets are served locally. Labels stay on the containing control.
const RemoteHubIcons = Object.freeze({
  server: 'server', overview: 'layout-dashboard', docker: 'boxes', terminal: 'terminal',
  folder: 'folder', project: 'folder-git-2', environment: 'layers', tasks: 'list-start',
  deepseek: 'deepseek', sun: 'sun', moon: 'moon', refresh: 'refresh-cw', password: 'key-round',
  logout: 'log-out', plus: 'plus', external: 'external-link', file: 'file', code: 'file-code',
  image: 'file-image', link: 'link', upload: 'upload', download: 'download', search: 'search',
  up: 'arrow-up', copy: 'copy', mkdir: 'folder-plus', delete: 'trash-2', rename: 'pencil',
  save: 'save', restore: 'archive-restore', start: 'play', stop: 'square', branch: 'git-branch',
  ssh: 'terminal', key: 'key-round', star: 'star', fingerprint: 'fingerprint',
  diagnose: 'activity', settings: 'settings-2', chevron: 'chevron-down',
  lock: 'lock-keyhole', shield: 'shield-check', close: 'x',
  cpu: 'cpu', memory: 'memory-stick', disk: 'hard-drive', network: 'network',
});
function icon(name) {
  const symbol = RemoteHubIcons[name];
  return symbol ? `<svg class="orh-icon" aria-hidden="true" focusable="false"><use href="/static/icons.svg#${symbol}"></use></svg>` : '';
}
