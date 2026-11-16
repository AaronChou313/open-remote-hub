'use strict';
window.RemoteHubFormControls = (() => {
  const escape = value => String(value ?? '').replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
  function list(selector, values, options = {}) {
    const root = document.querySelector(selector);
    root.innerHTML = '<div class="editable-list"></div><button type="button" class="list-add">添加' + escape(options.label || '地址') + '</button>';
    const rows = root.querySelector('.editable-list');
    function add(value = '') {
      const row = document.createElement('div');
      row.className = 'editable-list-row';
      row.innerHTML = `<input data-list-value aria-label="${escape(options.label || '地址')}" placeholder="${escape(options.placeholder || '')}" value="${escape(value)}"><button type="button" aria-label="移除此${escape(options.label || '地址')}">移除</button>`;
      row.querySelector('button').onclick = () => { row.remove(); options.onChange?.(); };
      row.querySelector('input').oninput = () => options.onChange?.();
      rows.append(row);
      return row;
    }
    values.forEach(value => add(value));
    root.querySelector('.list-add').onclick = () => { add().querySelector('input').focus(); options.onChange?.(); };
    return {values:() => [...rows.querySelectorAll('[data-list-value]')].map(input => input.value.trim()).filter(Boolean)};
  }
  function mappings(selector, entries, onChange) {
    const root = document.querySelector(selector);
    root.innerHTML = '<div class="port-mappings"></div><div class="toolbar"><select aria-label="选择服务模板"><option value="custom">自定义服务</option><option value="ssh">SSH</option><option value="http">HTTP</option><option value="https">HTTPS</option><option value="rustdesk">RustDesk</option></select><button type="button">添加映射</button></div>';
    const rows = root.querySelector('.port-mappings');
    function add(port = '', host = '127.0.0.1', local = '') {
      const row = document.createElement('div'); row.className = 'port-mapping-row';
      row.innerHTML = `<label>组网端口<input data-publish-port type="number" min="1" max="65535" required value="${escape(port)}"></label><span class="mapping-arrow" aria-hidden="true">→</span><label>本机地址<input data-publish-host required value="${escape(host)}"></label><label>本机端口<input data-publish-local type="number" min="1" max="65535" required value="${escape(local)}"></label><button type="button" aria-label="移除此端口映射">移除</button>`;
      row.querySelector('button').onclick = () => { row.remove(); onChange(); };
      row.oninput = onChange; rows.append(row);
    }
    Object.entries(entries).forEach(([port,address]) => { const value = new URL('http://' + address); add(port,value.hostname.replace(/^\[|\]$/g,''),value.port || address.slice(address.lastIndexOf(':')+1)); });
    root.querySelector('.toolbar button').onclick = () => {
      const port = {ssh:22,http:80,https:443,rustdesk:21118}[root.querySelector('select').value] || '';
      add(port,'127.0.0.1',port); onChange();
      rows.lastElementChild.querySelector('input').focus();
    };
    return {values:() => {
      const result = {};
      rows.querySelectorAll('.port-mapping-row').forEach(row => {
        const port = row.querySelector('[data-publish-port]').value;
        if (Object.hasOwn(result,port)) throw Error('组网端口重复，请为每个映射使用不同端口');
        const host = row.querySelector('[data-publish-host]').value.trim();
        const local = row.querySelector('[data-publish-local]').value;
        result[port] = (host.includes(':') ? '['+host+']' : host) + ':' + local;
      });
      return result;
    }};
  }
  const labels = {udp:'UDP',ipv4:'IPv4',ipv6:'IPv6',latency_ms:'延迟（毫秒）',latency_seconds:'延迟（秒）',route:'链路',endpoint:'端点',derp:'DERP 中继',peer:'目标设备',error:'说明',UDP:'UDP',IPv4:'IPv4',IPv6:'IPv6',MappingVariesByDestIP:'目的地址影响映射',HairPinning:'回环连接',UPnP:'UPnP',PMP:'NAT-PMP',PCP:'PCP',PreferredDERP:'首选 DERP',RegionLatency:'中继延迟',RegionV4Latency:'IPv4 中继延迟',RegionV6Latency:'IPv6 中继延迟'};
  function facts(value) {
    if (Array.isArray(value)) return value.length ? '<ul class="fact-list">'+value.map(item=>'<li>'+facts(item)+'</li>').join('')+'</ul>' : '<span class="muted">暂无记录</span>';
    if (value && typeof value === 'object') return '<dl class="settings-facts">'+Object.entries(value).map(([key,item])=>`<div><dt>${escape(labels[key] || key)}</dt><dd>${facts(item)}</dd></div>`).join('')+'</dl>';
    return escape(value === true ? '可用' : value === false ? '未检测到' : value == null || value === '' ? '暂无结果' : value);
  }
  return {escape,list,mappings,facts};
})();
