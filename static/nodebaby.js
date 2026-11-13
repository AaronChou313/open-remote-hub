"use strict";
window.RemoteHubNodeBaby = (() => {
  let state;
  let context;
  let group = "";
  let query = "";
  let probing = false;
  const results = new Map();
  const $ = (selector) => document.querySelector(selector);

  function markup() {
    return `<section id="rcNodeBaby" hidden>
      <div class="rc-tail-toolbar"><div class="rc-tail-actions">
        <button id="nbOpen" disabled>${icon("external")}在主机打开客户端</button>
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
      <div class="rc-peers"><div class="table-wrap"><table><thead><tr><th>设备 / 别名</th><th>组网地址</th><th>数据链路</th><th>服务检测</th><th>操作</th></tr></thead><tbody id="nbRows"></tbody></table></div></div>
      <p class="muted rc-node-footnote">映射来自本机客户端。数据链路按需建立，服务检测检查指定 TCP 端口。</p>
      <dialog id="nbProbeDialog"><form id="nbProbeForm"><h2>检测设备服务</h2>
        <p id="nbProbeTarget" class="mono"></p>
        <label>服务端口<input id="nbPort" type="number" min="1" max="65535" required value="8765" inputmode="numeric" list="nbPorts"></label>
        <datalist id="nbPorts"><option value="22">SSH</option><option value="80">HTTP</option><option value="443">HTTPS</option><option value="445">SMB</option><option value="3389">远程桌面</option><option value="8765">RemoteHub</option></datalist>
        <p id="nbProbeResult" role="status" hidden></p>
        <div class="dialog-actions"><button type="button" id="nbCloseProbe">关闭</button><button class="primary" type="submit" id="nbTest">检测</button></div>
      </form></dialog>
    </section>`;
  }

  function mount(options) {
    context = options;
    probing = false;
    group = "";
    query = "";
    results.clear();
    $("#nbSearch").oninput = (event) => {
      query = event.target.value.toLowerCase().trim();
      draw();
    };
    $("#nbGroup").onchange = (event) => {
      group = event.target.value;
      draw();
    };
    $("#nbRefresh").onclick = () => context.busy($("#nbRefresh"), context.refresh);
    $("#nbOpen").onclick = () => context.busy($("#nbOpen"), async () => {
      await api("/remote-connect/nodebaby/open", {});
      if (context.current()) notify("已在主机打开节点小宝");
    });
    $("#nbProbeDialog").addEventListener("cancel", (event) => {
      if (probing) event.preventDefault();
    });
    $("#nbCloseProbe").onclick = () => $("#nbProbeDialog").close();
    $("#nbProbeForm").onsubmit = (event) => {
      event.preventDefault();
      const owner = context;
      const id = $("#nbProbeForm").dataset.target;
      const port = Number($("#nbPort").value);
      context.busy($("#nbTest"), async () => {
        $("#nbProbeResult").hidden = false;
        $("#nbProbeResult").textContent = "正在连接…";
        probing = true;
        $("#nbCloseProbe").disabled = true;
        try {
          const result = await api("/remote-connect/nodebaby/probe", { id, port });
          if (context !== owner || !owner.current()) return;
          results.set(id, result);
          $("#nbProbeResult").textContent = result.reachable
            ? `${result.address}:${result.port} 可连接 · TCP 建连 ${result.latency_ms} ms`
            : `${result.address}:${result.port} ${result.message}`;
          draw();
        } catch (error) {
          if (context === owner && owner.current()) $("#nbProbeResult").textContent = error.message;
        } finally {
          probing = false;
          if (context === owner && owner.current()) $("#nbCloseProbe").disabled = false;
        }
      });
    };
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
  }

  function draw() {
    if (!state) return;
    const rows = state.mappings.filter((item) =>
      (group === "all" || item.group === group)
      && `${item.name} ${item.address} ${item.target}`.toLowerCase().includes(query));
    $("#nbRows").innerHTML = rows.map((item) => {
      const result = results.get(item.id);
      return `<tr><td><strong>${esc(item.name)}</strong><small>${item.self ? "本机" : `目标 ${esc(item.target)}`}</small></td>
        <td class="mono">${esc(item.address)}${item.prefix === 32 ? "" : `/${item.prefix}`}</td>
        <td>${item.self ? "本机映射" : item.link_active ? "链路已建立" : "按需连接"}</td>
        <td class="${result?.reachable ? "rc-node-success" : "muted"}">${result ? `${result.port} · ${result.reachable ? `${result.latency_ms} ms` : "未连通"}` : "未检测"}</td>
        <td><div class="rc-peer-actions"><button data-nb-probe="${esc(item.id)}" ${item.prefix !== 32 ? "disabled" : ""}>${icon("diagnose")}检测服务</button><button data-nb-copy="${esc(item.address)}">${icon("copy")}复制 IP</button></div></td></tr>`;
    }).join("") || '<tr><td colspan="5" class="muted">没有匹配的映射</td></tr>';
    document.querySelectorAll("[data-nb-copy]").forEach((button) => {
      button.onclick = () => context.busy(button, async () => {
        await context.copy(button.dataset.nbCopy);
        notify("组网地址已复制");
      });
    });
    document.querySelectorAll("[data-nb-probe]").forEach((button) => {
      button.onclick = () => {
        const item = state.mappings.find((item) => item.id === button.dataset.nbProbe);
        $("#nbProbeForm").dataset.target = item.id;
        $("#nbProbeTarget").textContent = item.address;
        $("#nbProbeResult").hidden = true;
        $("#nbProbeDialog").showModal();
      };
    });
  }

  function reset() {
    context = null;
    probing = false;
    state = null;
    results.clear();
  }
  return { markup, mount, update, reset };
})();
