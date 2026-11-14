export const STORAGE_KEY = 'openremotehub.hosts.v1';

export function normalizeURL(input) {
  const text = input.trim();
  const explicitScheme = /^[a-z][a-z\d+.-]*:/i.test(text) && text.includes('://');
  const url = new URL(explicitScheme ? text : 'http://' + text);
  if (!['http:', 'https:'].includes(url.protocol) || url.username || url.password || !url.hostname) {
    throw Error('请输入 HTTP 或 HTTPS 地址，不要在地址中包含密码。');
  }
  if (!explicitScheme && !url.port) url.port = '8765';
  return url.origin;
}

export function normalizeHost(value) {
  if (!value || !Array.isArray(value.urls) || !value.urls.length) throw Error('每台主机至少需要一个访问地址。');
  const urls = [...new Set(value.urls.map(normalizeURL))];
  return {
    id: crypto.randomUUID(),
    instanceId: typeof value.instanceId === 'string' ? value.instanceId.slice(0, 100) : null,
    name: typeof value.name === 'string' ? value.name.trim().slice(0, 120) : '',
    urls,
    preferred: urls.includes(value.preferred) ? value.preferred : null,
  };
}

export function isIdentity(value) {
  return value?.service === 'openremotehub' && value.protocol === 1 &&
    typeof value.instance_id === 'string' && /^[\da-f]{8}(-[\da-f]{4}){3}-[\da-f]{12}$/i.test(value.instance_id) &&
    typeof value.name === 'string' && value.name.length <= 253;
}

export function addressSpace(address) {
  const host = new URL(address).hostname.replace(/^\[|\]$/g, '').toLowerCase();
  if (host === 'localhost' || host.endsWith('.localhost') || host === '::1' || host.startsWith('127.')) return 'loopback';
  if (new URL(address).protocol === 'http:') return 'local';
  return undefined;
}

export function mergeIdentities(hosts, results) {
  const groups = new Map();
  const usedIds = new Set();
  for (const host of hosts) {
    const firstOnline = host.urls.map(url => results.get(url)).find(result => result?.identity);
    const fallback = host.instanceId || firstOnline?.identity.instance_id || host.id;
    for (const url of host.urls) {
      const identity = results.get(url)?.identity;
      const key = identity?.instance_id || fallback;
      let group = groups.get(key);
      if (!group) {
        const split = usedIds.has(host.id);
        group = {...host, id: split ? crypto.randomUUID() : host.id,
          instanceId: identity?.instance_id || host.instanceId,
          name: split ? identity?.name || host.name : host.name || identity?.name || '',
          urls: [], preferred: null};
        usedIds.add(group.id);
        groups.set(key, group);
      }
      if (!group.urls.includes(url)) group.urls.push(url);
      if (url === host.preferred) group.preferred = url;
    }
  }
  return [...groups.values()];
}

export function bestURL(host, results) {
  const online = host.urls.filter(url => results.get(url)?.identity);
  if (online.includes(host.preferred)) return host.preferred;
  return online.sort((a, b) => results.get(a).latency - results.get(b).latency)[0] || host.preferred || host.urls[0];
}
