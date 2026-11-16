"use strict";
window.RemoteHubAgentSettings = (() => {
  let dirty = false;
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
    if (dirty && document.querySelector("#agentAccessForm")) return;
    const data = await api("/agent/settings");
    if (!check()) return;
    document.querySelector(target).innerHTML =
      `<h2>Web 控制台与本地恢复</h2><form id="agentAccessForm" class="agent-access-form"><label for="agentBindAddress">监听地址<input id="agentBindAddress" value="${esc(data.bind)}" required placeholder="127.0.0.1 或 0.0.0.0"><small>127.0.0.1 供本机与内置 Mesh 使用。0.0.0.0 允许经局域网和独立组网访问。</small></label><label for="agentAllowedHosts">允许访问的本机 IP 或名称<textarea id="agentAllowedHosts" rows="3" placeholder="例如 192.168.1.20、10.77.1.2">${esc(data.allowed_hosts.join("\n"))}</textarea><small>每行一个地址，可填写官方 Tailscale、节点小宝等备用网络 IP。</small></label><label class="switch-row"><span>启用独立本地恢复密码</span><input id="agentRecovery" type="checkbox" ${data.recovery_enabled ? "checked" : ""}></label><label for="agentRecoveryPassword">${data.recovery_enabled ? "更换恢复密码" : "设置恢复密码"}<input id="agentRecoveryPassword" type="password" autocomplete="new-password" minlength="8" placeholder="${data.recovery_enabled ? "留空保留当前密码" : "至少 8 个字符"}"></label><p class="muted">Cloud 不可用时，在目标 Web 控制台选择本地恢复登录。该密码由目标 Agent 本地校验。</p><p id="agentAccessError" role="alert" class="detail-error"></p><p id="agentAccessNotice" role="status">${esc((data.listener_errors||[]).join(" · ")) || (data.restart_required ? "监听地址已保存，重启后台后生效。" : "")}</p><div class="toolbar"><button id="agentAccessSave" type="submit" class="primary">保存访问设置</button>${data.restart_required && data.restart_supported ? '<button id="agentRestart" type="button">重启后台并应用</button>' : ""}</div></form><div class="agent-access-urls">${data.urls.map((url) => `<p><a href="${esc(url)}" target="_blank" rel="noopener">${esc(url)}</a></p>`).join("")}</div><details><summary>备用网络访问</summary><p>独立运行的 Tailscale、节点小宝由其自身客户端管理。使用允许列表中的目标 IP 访问 Web 控制台，或在对应软件中连接 SSH、RustDesk。</p><a class="button" href="/#lan">本机局域网与网络工具</a></details>`;
    const $ = (s) => document.querySelector(s);
    $("#agentAccessForm").oninput = () => {
      dirty = true;
    };
    $("#agentAccessForm").onsubmit = async (event) => {
      event.preventDefault();
      const button = $("#agentAccessSave");
      button.disabled = true;
      try {
        await api("/agent/settings", {
          bind: $("#agentBindAddress").value.trim(),
          allowed_hosts: $("#agentAllowedHosts")
            .value.split(/[\s,，]+/)
            .filter(Boolean),
          recovery_enabled: $("#agentRecovery").checked,
          password: $("#agentRecoveryPassword").value,
        });
        dirty = false;
        if (check()) await render(check, target, api);
      } catch (error) {
        if (check()) $("#agentAccessError").textContent = error.message;
      } finally {
        if (button.isConnected) button.disabled = false;
      }
    };
    if ($("#agentRestart"))
      $("#agentRestart").onclick = async () => {
        if (
          !window.confirm(
            "重启目标后台会中断控制台、Mesh 和终端连接。Windows 的终端会话将结束。现在重启？",
          )
        )
          return;
        $("#agentRestart").disabled = true;
        try {
          await api("/agent/settings/restart", {});
          $("#agentAccessNotice").textContent =
            "后台正在重启，请稍后刷新控制台。";
        } catch (error) {
          $("#agentAccessError").textContent = error.message;
        }
      };
  }
  async function canLeave() {
    if (!dirty) return true;
    if (!window.confirm("放弃尚未保存的访问设置？")) return false;
    dirty = false;
    return true;
  }
  return {
    render,
    canLeave,
    reset: () => {
      dirty = false;
    },
  };
})();
