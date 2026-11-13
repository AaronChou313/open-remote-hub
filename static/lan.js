"use strict";
window.RemoteHubLAN = (() => {
  const $ = (selector) => document.querySelector(selector);
  let context, data, request;
  let scanning = false;
  let search = "";
  let onlineOnly = false;
  function markup() {
    return `<section id="rcLAN"><div id="lanInterfaces" class="lan-interfaces"></div>
      <details class="lan-dns"><summary>系统 DNS</summary><div id="lanDNS" class="mono"></div></details>
      <div class="lan-toolbar"><input id="lanSearch" type="search" aria-label="搜索局域网设备" placeholder="搜索设备、备注、IP 或 MAC"><label class="rc-online-filter"><input id="lanOnlineOnly" type="checkbox">仅在线</label><button id="lanScan" class="primary">${icon("search")}发现设备</button></div>
      <p id="lanMessage" class="muted" role="status"></p><div id="lanDevices" class="rc-peers"></div></section>`;
  }
  function mount(options) {
    context = options; data = null; request = null; scanning = false; search = ""; onlineOnly = false;
    $("#lanSearch").oninput = (event) => { search = event.target.value.toLowerCase(); drawDevices(); };
    $("#lanOnlineOnly").onchange = (event) => { onlineOnly = event.target.checked; drawDevices(); };
    $("#lanScan").onclick = async () => {
      if (scanning) return;
      const owner = context;
      scanning = true;
      $("#lanScan").disabled = true;
      $("#lanScan").textContent = "正在发现…";
      $("#lanMessage").textContent = "正在检测当前局域网，通常需要数秒…";
      try {
        await request;
        const result = await api("/remote-connect/lan/scan", {});
        if (context === owner && owner.current()) update(result);
      } catch (error) {
        if (context === owner && owner.current()) $("#lanMessage").textContent = error.message;
      } finally {
        if (context === owner) {
          scanning = false;
          if (owner.current()) { $("#lanScan").disabled = false; $("#lanScan").innerHTML = icon("search") + "发现设备"; }
        }
      }
    };
  }
  async function refresh() {
    if (scanning) return;
    if (request) return request;
    const owner = context;
    const pending = api("/remote-connect/lan").then((value) => { if (context === owner && owner.current()) update(value); });
    request = pending;
    try { await pending; } finally { if (request === pending) request = null; }
  }
  function update(value) {
    data = value;
    $("#lanInterfaces").innerHTML = value.interfaces.map((link) => {
      const gateways = value.gateways.filter((row) => row.interface === link.name).map((row) => row.address);
      return `<article class="lan-interface"><div class="lan-interface-title"><h2>${icon("network")}网络接口 ${esc(link.name)}</h2><span class="rc-dot online">已连接</span></div><p class="lan-address mono">${esc(link.ip)}</p><dl><div><dt>网段</dt><dd>${esc(link.network)}</dd></div><div><dt>网关</dt><dd>${esc(gateways.join(" · ") || "—")}</dd></div><div><dt>掩码</dt><dd>${esc(link.netmask)}</dd></div><div><dt>链路速率</dt><dd>${link.speed_mbps ? link.speed_mbps + " Mbps" : "—"}</dd></div></dl><div class="lan-traffic"><span>↑ ${link.upload == null ? "采样中" : bytes(link.upload) + "/s"}</span><span>↓ ${link.download == null ? "采样中" : bytes(link.download) + "/s"}</span></div></article>`;
    }).join("") || empty("未发现已连接的本地网络接口");
    $("#lanDNS").textContent = value.dns.join(" · ") || "暂不可用";
    $("#lanMessage").textContent = `${value.devices.length} 台已发现设备` + (value.warnings.length ? " · " + value.warnings.join(" · ") : "");
    drawDevices();
  }
  function drawDevices() {
    if (!data) return;
    const rows = data.devices.filter((row) => (!onlineOnly || ["self","online"].includes(row.state)) && `${row.name || ""} ${row.note} ${row.addresses.join(" ")} ${row.mac}`.toLowerCase().includes(search));
    const labels = {self:"本机", online:"在线", unresponsive:"未响应", known:"已发现"};
    $("#lanDevices").innerHTML = table(["设备", "IP 地址", "MAC / 接口", "状态", "检测时间", "操作"], rows.map((row) => `<tr><td><strong>${esc(row.note || row.name || (row.gateway ? "网关" : "局域网设备"))}</strong>${row.gateway && (row.note || row.name) ? '<small>网关</small>' : ""}</td><td class="mono">${row.addresses.map(esc).join("<br>")}</td><td><span class="mono">${row.macs.map(esc).join("<br>") || "—"}</span><small>${esc(row.interfaces.join(" · "))}</small></td><td><span class="rc-peer-status ${["online","self"].includes(row.state) ? "online" : "unknown"}" title="${row.state === "unresponsive" ? "未收到检测响应，设备可能休眠或禁止响应" : ""}">${labels[row.state]}</span></td><td>${row.checked_at ? new Date(row.checked_at * 1000).toLocaleTimeString() : row.last_seen ? new Date(row.last_seen * 1000).toLocaleString() : "—"}</td><td><div class="rc-peer-actions"><button data-lan-copy="${esc(row.id)}">${icon("copy")}复制 IP</button><button data-lan-note="${esc(row.id)}">${icon("rename")}备注</button></div></td></tr>`));
    document.querySelectorAll("[data-lan-copy]").forEach((button) => { button.onclick = async () => {
      try { await context.copy(data.devices.find((row) => row.id === button.dataset.lanCopy).addresses[0]); notify("IP 已复制"); } catch (error) { showError(error); }
    }; });
    document.querySelectorAll("[data-lan-note]").forEach((button) => { button.onclick = async () => {
      const owner = context;
      const row = data.devices.find((row) => row.id === button.dataset.lanNote);
      const note = await requestName("设备备注", row.note, "保存", 120, true);
      if (note == null || context !== owner || !owner.current()) return;
      try { await api("/remote-connect/lan/note", {id:row.id,note}); await refresh(); } catch (error) { showError(error); }
    }; });
  }
  function reset() { context = null; data = null; }
  return {markup, mount, refresh, reset};
})();
