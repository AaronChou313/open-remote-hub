"use strict";
window.RemoteHubNodeBaby = (() => {
  let state;
  let context;
  let group = "";
  let query = "";
  let checking = false;
  let nextCheck = 0;
  const $ = (selector) => document.querySelector(selector);

  function markup() {
    return `<section id="rcNodeBaby" hidden>
      <div class="rc-tail-toolbar"><div class="rc-tail-actions">
        <button id="nbOpen" disabled>${icon("external")}在主机打开客户端</button>
        <button id="nbCheckAll">${icon("diagnose")}全部检测</button><label class="rc-online-filter"><input type="checkbox" id="nbAutoCheck" checked>自动检测</label>
        <button id="nbRefresh">${icon("refresh")}刷新状态</button>
      </div><a class="button" href="https://yc.iepose.com/" target="_blank" rel="noopener">节点小宝管理后台 ${icon("external")}</a></div>
      <p id="nbError" class="rc-error" role="alert" hidden></p>
      <dl class="rc-tail-identity rc-node-identity">
        <div><dt>服务版本</dt><dd id="nbVersion">—</dd></div>
        <div><dt>虚拟网卡</dt><dd id="nbTun">—</dd></div>
        <div><dt>后台进程</dt><dd id="nbPid">—</dd></div>
        <div><dt>本机名称</dt><dd id="nbHostname">—</dd></div>
      </dl>
      <div class="rc-peer-toolbar">
        <input id="nbSearch" type="search" aria-label="搜索节点小宝映射" placeholder="搜索设备、别名或 IP">
        <label class="rc-node-group">网段<select id="nbGroup" aria-label="节点小宝映射网段"></select></label>
      </div>
      <div class="rc-peers"><div class="table-wrap"><table><thead><tr><th>设备 / 别名</th><th>组网地址</th><th>状态</th><th>连接</th><th>最近检测</th><th>操作</th></tr></thead><tbody id="nbRows"></tbody></table></div></div>
      <p class="muted rc-node-footnote">状态每 5 秒刷新，自动检测每 15 秒运行。未连通时可检查设备和节点小宝连接。</p>
    </section>`;
  }

  function mount(options) {
    context = options;
    checking = false;
    nextCheck = 0;
    group = "";
    query = "";
    $("#nbSearch").oninput = (event) => {
      query = event.target.value.toLowerCase().trim();
      draw();
    };
    $("#nbGroup").onchange = (event) => {
      group = event.target.value;
      nextCheck = 0;
      draw();
      maybeCheck();
    };
    $("#nbCheckAll").onclick = () => checkDevices(visibleRows().filter((item) => item.prefix === 32).map((item) => item.id));
    $("#nbAutoCheck").onchange = () => { nextCheck = 0; maybeCheck(); };
    $("#nbRefresh").onclick = () => context.busy($("#nbRefresh"), context.refresh);
    $("#nbOpen").onclick = () => context.busy($("#nbOpen"), async () => {
      await api("/remote-connect/nodebaby/open", {});
      if (context.current()) notify("已在主机打开节点小宝");
    });
  }

  function update(value) {
    state = value;
    if (!state) return;
    const online = state.connected && state.tun_ready;
    $("#nbState").textContent = !state.available ? "未安装" : !state.ready ? "服务未就绪" : online ? "已连接" : "正在连接";
    $("#nbState").classList.toggle("online", online);
    const preferred = state.addresses.find((address) => address === location.hostname)
      || state.addresses.find((address) => address.startsWith("10.")) || state.addresses[0];
    $("#nbAddress").textContent = preferred || "—";
    $("#nbSummary").textContent = `${state.mappings.length} 条原生映射`;
    $("#nbVersion").textContent = state.version || "—";
    $("#nbTun").textContent = state.ready ? (state.tun_ready ? "已就绪" : "未就绪") : "—";
    $("#nbPid").textContent = state.pid ? `PID ${state.pid}` : "—";
    $("#nbHostname").textContent = state.hostname || "—";
    $("#nbOpen").disabled = !state.can_open;
    $("#nbError").textContent = [state.error, state.transport_error].filter(Boolean).join("\n");
    $("#nbError").hidden = !$("#nbError").textContent;
    const groups = [...new Set(state.mappings.map((item) => item.group))];
    if (!group) group = state.mappings.find((item) => item.address === preferred)?.group || "all";
    if (group !== "all" && !groups.includes(group)) group = "all";
    $("#nbGroup").innerHTML = '<option value="all">所有映射</option>'
      + groups.map((value) => `<option value="${esc(value)}">${esc(value)}</option>`).join("");
    $("#nbGroup").value = group;
    draw();
    maybeCheck();
  }

  function draw() {
    if (!state) return;
    const rows = visibleRows();
    $("#nbRows").innerHTML = rows.map((item) => {
      const connection = item.connection || {state: "unknown", route: "等待检测"};
      const label = {self: "本机", online: "在线", unreachable: "未连通", unknown: "待检测"}[connection.state];
      return `<tr><td><strong>${esc(item.name)}</strong><small>${item.self ? "本机" : `目标 ${esc(item.target)}`}</small></td>
        <td class="mono">${esc(item.address)}${item.prefix === 32 ? "" : `/${item.prefix}`}</td>
        <td><span class="rc-peer-status ${esc(connection.state)}">${label}</span></td>
        <td>${esc(connection.route)}${connection.latency_ms == null ? "" : ` · ${connection.latency_ms} ms`}</td>
        <td>${connection.checked_at ? new Date(connection.checked_at * 1000).toLocaleTimeString() : "—"}</td>
        <td><div class="rc-peer-actions"><button data-nb-check="${esc(item.id)}" ${checking || item.prefix !== 32 ? "disabled" : ""}>${icon("diagnose")}检测</button><button data-nb-copy="${esc(item.address)}">${icon("copy")}复制 IP</button></div></td></tr>`;
    }).join("") || '<tr><td colspan="6" class="muted">没有匹配的映射</td></tr>';
    document.querySelectorAll("[data-nb-check]").forEach((button) => {
      button.onclick = () => checkDevices([button.dataset.nbCheck]);
    });
    document.querySelectorAll("[data-nb-copy]").forEach((button) => {
      button.onclick = () => context.busy(button, async () => {
        await context.copy(button.dataset.nbCopy);
        notify("组网地址已复制");
      });
    });
  }

  function visibleRows() {
    return (state?.mappings || []).filter((item) =>
      (group === "all" || item.group === group)
      && `${item.name} ${item.address} ${item.target}`.toLowerCase().includes(query));
  }

  async function checkDevices(ids) {
    if (checking || !ids.length) return;
    const owner = context;
    checking = true;
    nextCheck = Date.now() + 15000;
    $("#nbCheckAll").disabled = true;
    $("#nbCheckAll").textContent = "正在检测…";
    draw();
    try {
      const result = await api("/remote-connect/nodebaby/check", {ids});
      if (owner !== context || !owner.current()) return;
      update(result);
    } catch (error) {
      if (owner === context && owner.current()) {
        $("#nbError").textContent = error.message;
        $("#nbError").hidden = false;
      }
    } finally {
      if (owner === context) {
        checking = false;
        if (owner.current()) {
          $("#nbCheckAll").disabled = false;
          $("#nbCheckAll").innerHTML = icon("diagnose") + "全部检测";
          draw();
        }
      }
    }
  }

  function maybeCheck() {
    if (!state?.ready || $("#rcNodeBaby").hidden || checking || !$("#nbAutoCheck").checked || Date.now() < nextCheck) return;
    checkDevices(visibleRows().filter((item) => item.prefix === 32).map((item) => item.id));
  }

  function reset() {
    context = null;
    state = null;
  }
  return { markup, mount, update, reset, maybeCheck };
})();
