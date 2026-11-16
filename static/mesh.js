"use strict";
window.RemoteHubMesh = (() => {
  let dirty = false;
  let reportText = "";
  const esc = (value) =>
    String(value ?? "").replace(
      /[&<>"']/g,
      (c) =>
        ({
          "&": "&amp;",
          "<": "&lt;",
          ">": "&gt;",
          '"': "&quot;",
          "'": "&#39;",
        })[c],
    );
  async function render(check, target, api) {
    if (dirty && document.querySelector("#meshRoot")) return;
    const data = await api("/client/mesh");
    if (!check()) return;
    const status = data.status,
      device = status.device || {},
      peers = status.peers || [];
    const labels = {
      Running: "已连接",
      Stopped: "已断开",
      NeedsLogin: "需要登录",
      Starting: "连接中",
    };
    document.querySelector(target).innerHTML =
      `<section id="meshRoot"><dl class="client-details"><div><dt>本机组网</dt><dd>${esc(status.error || labels[status.state] || status.state || "未连接")}</dd></div><div><dt>设备名称</dt><dd>${esc(device.hostname || "—")}</dd></div><div><dt>组网 IP</dt><dd>${esc((device.addresses || []).join(" · ") || "—")}</dd></div><div><dt>设备连通性</dt><dd>${peers.filter((p) => p.online).length} / ${peers.length} 台在线</dd></div></dl>
  <div class="toolbar"><button id="meshReconnect">重新连接</button><button id="meshNetcheck">网络诊断</button></div><p id="meshError" class="detail-error" role="alert"></p><div id="meshReport" class="mesh-report" ${reportText?"":"hidden"}>${reportText}</div>
  <h2>设备连接与 TCP 转发</h2><form id="meshForwardForm" class="mesh-form"><label for="meshPeer">目标设备<select id="meshPeer" required>${peers.flatMap((peer) => (peer.addresses || []).filter((ip) => !ip.includes(":")).map((ip) => `<option value="${esc(ip)}">${esc(peer.hostname || peer.dns || ip)} · ${esc(ip)} · ${peer.route === "direct" ? "P2P 直连" : peer.route === "relay" ? "DERP 中继" : "待连接"}</option>`)).join("")}</select></label><label for="meshRemotePort">目标 TCP 端口<input id="meshRemotePort" type="number" min="1" max="65535" required placeholder="例如 22、80、21118"></label><label for="meshLocalPort">本地端口<input id="meshLocalPort" type="number" min="0" max="65535" value="0" required><small>填写 0 自动分配</small></label><div class="toolbar"><button id="meshForward" class="primary" type="submit">创建转发</button><button id="meshPing" type="button">检测连接</button></div></form>
  <div class="table-wrap"><table><thead><tr><th>本地入口</th><th>目标</th><th>连接数</th><th>操作</th></tr></thead><tbody>${data.forwards.map((row) => `<tr><td class="mono">127.0.0.1:${row.local_port}</td><td>${esc(row.peer_ip)}:${row.remote_port}</td><td>${row.connections}</td><td><button data-mesh-close="${esc(row.id)}">关闭转发</button></td></tr>`).join("") || '<tr><td colspan="4">暂无转发通道</td></tr>'}</tbody></table></div><details id="meshConfig"><summary>本机组网与发布端口</summary><div id="meshConfigFields"></div></details></section>`;
    const $ = (s) => document.querySelector(s);
    async function action(button, work) {
      button.disabled = true;
      $("#meshError").textContent = "";
      try {
        await work();
      } catch (error) {
        if (check()) $("#meshError").textContent = error.message;
      } finally {
        if (button.isConnected) button.disabled = false;
      }
    }
    function report(value) {
      reportText=RemoteHubFormControls.facts(value);
      $("#meshReport").hidden = false;
      $("#meshReport").innerHTML = reportText;
    }
    $("#meshConfig").ontoggle = async () => {
      if (!$("#meshConfig").open || $("#meshConfigForm")) return;
      try {
        const config = await api("/remote-connect/mesh/config");
        if (!check()) return;
        $("#meshConfigFields").innerHTML =
          `<form id="meshConfigForm" class="agent-access-form"><label for="meshHostname">设备名称<input id="meshHostname" value="${esc(config.hostname)}" required></label><label for="meshControl">Headscale 地址<input id="meshControl" type="url" value="${esc(config.control_url)}" required></label><fieldset><legend>发布到组网的服务</legend><div id="meshPublish"></div></fieldset><button id="meshConfigSave" class="primary">保存并重新连接</button></form>`;
        const mappings = RemoteHubFormControls.mappings("#meshPublish", config.publish, () => { dirty = true; });
        $("#meshConfigForm").oninput = () => {
          dirty = true;
        };
        $("#meshConfigForm").onsubmit = (event) => {
          event.preventDefault();
          action($("#meshConfigSave"), async () => {
            const publish = mappings.values();
            if (
              !window.confirm(
                "保存后将重新连接目标 Mesh，现有组网通道会暂时中断。继续保存？",
              )
            )
              return;
            await api("/remote-connect/mesh/config", {
              hostname: $("#meshHostname").value,
              control_url: $("#meshControl").value,
              publish,
            });
            dirty = false;
            if (check()) await render(check, target, api);
          });
        };
      } catch (error) {
        if (check()) $("#meshError").textContent = error.message;
      }
    };
    $("#meshForwardForm").oninput = () => {
      dirty = true;
    };
    $("#meshForwardForm").onsubmit = (event) => {
      event.preventDefault();
      action($("#meshForward"), async () => {
        await api("/client/mesh/forward", {
          peer_ip: $("#meshPeer").value,
          remote_port: Number($("#meshRemotePort").value),
          local_port: Number($("#meshLocalPort").value),
        });
        dirty = false;
        if (check()) await render(check, target, api);
      });
    };
    $("#meshPing").onclick = () =>
      action($("#meshPing"), async () =>
        report(
          await api("/client/mesh/ping", { peer_ip: $("#meshPeer").value }),
        ),
      );
    $("#meshNetcheck").onclick = () =>
      action($("#meshNetcheck"), async () =>
        report(await api("/client/mesh/netcheck", {})),
      );
    $("#meshReconnect").onclick = () =>
      action($("#meshReconnect"), async () => {
        await api("/client/mesh/control", { action: "reconnect" });
        dirty = false;
        if (check()) await render(check, target, api);
      });
    document.querySelectorAll("[data-mesh-close]").forEach(
      (button) =>
        (button.onclick = () =>
          action(button, async () => {
            await api("/client/mesh/close", { id: button.dataset.meshClose });
            if (check()) await render(check, target, api);
          })),
    );
  }
  async function canLeave() {
    if (!dirty) return true;
    if (!window.confirm("放弃尚未保存的组网设置？")) return false;
    dirty = false;
    return true;
  }
  return {
    render,
    canLeave,
    reset: () => {
      dirty = false;
      reportText = "";
    },
  };
})();
