"use strict";
window.RemoteHubRemoteConnect = (() => {
  const $ = (selector) => document.querySelector(selector);
  let current = () => false;
  let state;
  let original = {};
  let effectiveOriginal = {};
  let tab = "status";
  let requestedTab;
  let proxyVersion = 0;
  let operation = false;
  let dirty = false;
  let loadingSettings = false;
  let tailDirty = false;
  let tailOriginal = {};
  let network;
  let lanUrls = [];
  let query = "";
  let onlyOnline = false;
  let expectedDisconnect = false;
  const rdApi = (path, body) => api("/remote-connect/rustdesk" + path, body);
  const confirm = (title, message) => confirmAction(title, message);
  async function busy(button, work) {
    if (operation) return;
    operation = true;
    if (button) {
      button.disabled = true;
      button.setAttribute("aria-busy", "true");
    }
    try {
      await controller?.settle();
      await withBusy(null, "remote:operation", "", work);
    } catch (error) {
      if (current()) showError(error);
    } finally {
      operation = false;
      if (button?.isConnected) {
        button.disabled = false;
        button.removeAttribute("aria-busy");
      }
    }
  }
  async function copy(value) {
    if (navigator.clipboard && window.isSecureContext)
      return navigator.clipboard.writeText(value);
    const input = document.createElement("textarea");
    input.value = value;
    input.setAttribute("readonly", "");
    document.body.append(input);
    input.select();
    const copied = document.execCommand("copy");
    input.remove();
    if (!copied) throw Error("复制未成功，请手动选中内容复制");
  }
  async function renderProxy() {
    const version = ++proxyVersion;
    return RemoteHubProxy.render(() => current() && tab === "proxy" && version === proxyVersion, "#rcNetworkProxy", updateProxySummary);
  }
  function updateProxySummary(data, manager) {
    const engine = manager.engine;
    const active = manager.profiles.find((profile) => profile.active);
    const running = data.available && (!manager.managed || engine.enabled);
    $("#rcProxyState").textContent = running ? "运行中" : manager.managed
      ? !engine.ready ? "后台离线" : engine.enabled ? "内核未就绪" : "已停止"
      : "未连接";
    $("#rcProxyState").classList.toggle("online", running);
    $("#rcProxyAddress").textContent = manager.managed
      ? active?.name || "尚未选择配置" : running ? "Clash / Mihomo" : "代理控制器不可用";
    const modes = {rule: "规则模式", global: "全局模式", direct: "直连模式"};
    $("#rcProxySummary").textContent = running
      ? `${modes[data.mode] || data.mode} · ${data.connection_count} 个连接 · TUN ${data.tun_enabled ? "已启用" : "未启用"}`
      : manager.managed && engine.ready ? "Mihomo 后台已就绪" : "进入网络代理查看详情";
  }
  async function refreshProxySummary() {
    const owner = current;
    try {
      const [data, manager] = await Promise.all([api("/proxy"), api("/proxy/manager")]);
      if (owner()) updateProxySummary(data, manager);
    } catch (error) {
      if (!owner()) return;
      $("#rcProxyState").textContent = "读取失败";
      $("#rcProxyState").classList.remove("online");
      $("#rcProxyAddress").textContent = error.message;
      $("#rcProxySummary").textContent = "";
    }
  }
  function bindRustdesk() {
    let statusRequest;
    function updateStatus(value) {
      state = value;
      $("#rcOnline").textContent = value.ready
        ? value.accepting
          ? value.online
            ? "在线"
            : "正在连接网络"
          : "已暂停接入"
        : "客户端未就绪";
      $("#rcOnline").classList.toggle(
        "online",
        value.ready && value.online && value.accepting,
      );
      $("#rcDeviceId").value = value.device_id || "—";
      $("#rcCopyId").disabled = !value.device_id;
      $("#rcConnectHere").href = value.device_id
        ? "rustdesk://connection/new/" + encodeURIComponent(value.device_id)
        : "#";
      $("#rcConnectHere").setAttribute(
        "aria-disabled",
        String(!value.device_id),
      );
      $("#rcVersion").textContent = value.version
        ? "v" + value.version
        : value.installed
          ? "已安装"
          : "未安装";
      $("#rcAccepting").textContent = value.ready
        ? value.accepting
          ? "已启用"
          : "已暂停"
        : "未就绪";
      $("#rcConnections").textContent =
        value.connections === null ? "—" : value.connections + " 个连接";
      $("#rcPasswordSet").textContent =
        value.permanent_password_set === null
          ? "—"
          : value.permanent_password_set
            ? "已设置"
            : "未设置";
      $("#rcProcesses").textContent =
        value.processes.map((process) => "PID " + process.pid).join(" · ") ||
        "未运行";
      $("#rcAutostart").checked = value.autostart;
      $("#rcServiceToggle").textContent =
        value.ready && value.accepting ? "暂停接入" : "启动接入服务";
      $("#rcServiceRestart").disabled = !value.ready;
      $("#rcCopyTemporary").disabled = !value.ready;
      if (!value.ready) $("#rcTemporaryValue").value = "";
      $("#rcNativeMessage").textContent = value.message || "";
      $("#rcNativeMessage").hidden = !value.message;
    }
    async function refresh() {
      if (statusRequest) return statusRequest;
      const owner = current;
      const request = api("/remote-connect").then((data) => {
        if (!owner()) return;
        updateStatus(data.rustdesk);
        RemoteHubNodeBaby.update(data.nodebaby);
        updateNetwork(data.tailscale, data.lan_urls);
        $("#updated").textContent = "更新于 " + new Date().toLocaleTimeString();
        if (tab === "overview" && data.rustdesk.ready) return loadSettings();
        if (tab === "status") return Promise.all([RemoteHubLAN.refresh(), refreshProxySummary()]);
        if (tab === "lan") return RemoteHubLAN.refresh();
      });
      statusRequest = request;
      try {
        await request;
      } finally {
        if (statusRequest === request) statusRequest = null;
      }
    }
    $("#rcCopyId").onclick = () =>
      busy($("#rcCopyId"), async () => {
        await copy(state.device_id);
        notify("ID 已复制");
      });
    $("#rcConnectHere").onclick = (event) => {
      if (!state?.device_id) event.preventDefault();
    };
    $("#rcOpenNative").onclick = () =>
      busy($("#rcOpenNative"), async () => {
        await rdApi("/service", { action: "open" });
        notify("已在主机打开 RustDesk");
      });
    $("#rcAutostart").onchange = () => {
      const checkbox = $("#rcAutostart");
      const enabled = checkbox.checked;
      busy(checkbox, async () => {
        try {
          await rdApi("/autostart", { enabled });
          notify(enabled ? "已开启登录后自动运行" : "已关闭登录后自动运行");
        } catch (error) {
          checkbox.checked = !enabled;
          throw error;
        }
      });
    };
    $("#rcServiceToggle").onclick = () =>
      busy($("#rcServiceToggle"), async () => {
        const action = state?.ready && state.accepting ? "stop" : "start";
        if (
          action === "stop" &&
          !(await confirm(
            "暂停接入",
            "将暂停 RustDesk 接入服务。需要远程控制此 Mac 的设备可能需要重新连接。",
          ))
        )
          return;
        await rdApi("/service", { action, confirm: action === "stop" });
        await refresh();
        notify(action === "start" ? "接入服务已启动" : "已暂停接入");
      });
    $("#rcServiceRestart").onclick = () =>
      busy($("#rcServiceRestart"), async () => {
        if (
          !(await confirm(
            "重新连接接入服务",
            "将重新注册 RustDesk 连接服务，远程设备可能需要重新连接。",
          ))
        )
          return;
        await rdApi("/service", { action: "restart", confirm: true });
        await refresh();
        notify("已重新连接接入服务");
      });
    $("#rcCopyTemporary").onclick = () =>
      busy($("#rcCopyTemporary"), async () => {
        await copy($("#rcTemporaryValue").value);
        notify("密码已复制");
      });
    function normalized(key, value) {
      return key.startsWith("enable-") ? value !== "N" : value === "Y";
    }
    function changes() {
      const result = {};
      document
        .querySelectorAll(".remote-connect [data-option]")
        .forEach((input) => {
          const key = input.dataset.option;
          if (input.type === "checkbox") {
            if (input.checked !== normalized(key, effectiveOriginal[key]))
              result[key] = input.checked ? "Y" : "N";
          } else if (input.type === "radio") {
            if (input.checked && input.value !== effectiveOriginal[key]) result[key] = input.value;
          } else if (input.value.trim() !== effectiveOriginal[key])
            result[key] = input.value.trim();
        });
      return result;
    }
    function markDirty() {
      dirty = Object.keys(changes()).length > 0;
      $("#rcDirty").hidden = !dirty;
    }
    function fillSettings(options, effective, preserve = true) {
      const edits = preserve ? changes() : {};
      document.querySelectorAll(".remote-connect [data-option]").forEach((input) => {
        const key = input.dataset.option;
        if (key in edits) return;
        original[key] = options[key];
        effectiveOriginal[key] = effective[key];
        if (input.type === "radio") input.checked = input.value === effective[key];
        else if (input.type === "checkbox") input.checked = normalized(key, effective[key]);
        else input.value = effective[key] || "";
      });
      const passwordMode = document.querySelector('[data-option="approve-mode"]').value;
      $("#rcPasswordOptions").hidden = passwordMode === "click";
      const method = document.querySelector('[data-option="verification-method"]:checked')?.value;
      $("#rcTemporaryOptions").disabled = method === "use-permanent-password";
      $("#rcChangePassword").disabled = method === "use-temporary-password";
      markDirty();
    }
    async function loadSettings() {
      const owner = current;
      loadingSettings = true;
      try {
        const result = await rdApi("/live");
        if (!owner()) return;
        fillSettings(result.options, result.effective, Object.keys(original).length > 0);
        $("#rcTemporaryValue").value = result.temporary_password || "";
        $("#rcTemporaryValue").placeholder = result.temporary_enabled ? "暂不可用" : "当前验证方式已停用临时密码";
        $("#rcCopyTemporary").disabled = !result.temporary_password;
      } finally {
        loadingSettings = false;
      }
    }
    async function saveSettings(patch) {
      const controls = [...$("#rcSettingsForm").querySelectorAll("input,select,button")];
      controls.forEach((control) => control.disabled = true);
      try {
        await rdApi("/settings", {changes: patch, before: original});
        for (const key of Object.keys(patch)) {
          original[key] = patch[key];
          effectiveOriginal[key] = patch[key];
        }
        await loadSettings();
        notify("已同步到 RustDesk");
      } catch (error) {
        // Restore changed controls from a fresh native read while retaining other drafts.
        for (const key of Object.keys(patch)) effectiveOriginal[key] = optionValue(key);
        await loadSettings();
        throw error;
      } finally {
        controls.forEach((control) => control.disabled = false);
        const method = document.querySelector('[data-option="verification-method"]:checked')?.value;
        $("#rcTemporaryOptions").disabled = method === "use-permanent-password";
        $("#rcChangePassword").disabled = method === "use-temporary-password";
      }
    }
    function optionValue(key) {
      const inputs = [...document.querySelectorAll(`[data-option="${key}"]`)];
      const input = inputs.find((item) => item.type !== "radio" || item.checked);
      return input.type === "checkbox" ? (input.checked ? "Y" : "N") : input.value.trim();
    }
    $("#rcSettingsForm").oninput = () => { if (!loadingSettings) markDirty(); };
    $("#rcSettingsForm").onchange = (event) => {
      if (loadingSettings) return;
      markDirty();
      const input = event.target.closest("[data-live-option]");
      if (!input) return;
      const key = input.dataset.option;
      const value = optionValue(key);
      busy(input, () => saveSettings({[key]: value}));
    };
    $("#rcSettingsForm").onsubmit = (event) => {
      event.preventDefault();
      const patch = changes();
      if (Object.keys(patch).length) busy($("#rcSaveSettings"), () => saveSettings(patch));
    };
    async function selectTab(next, button) {
      return busy(button, async () => {
          if (next === tab) return;
          if (tab === "proxy" && !await RemoteHubProxyManager.canLeave()) return;
          if (tab === "proxy") proxyVersion++;
          if (
            (dirty || tailDirty) &&
            !(await confirm(
              "放弃未保存的修改",
              "离开设置将丢弃本次尚未保存的修改。",
            ))
          )
            return;
          if (dirty) fillSettings(original, effectiveOriginal, false);
          if (next === "overview") await loadSettings();
          else {
            dirty = false;
            $("#rcDirty").hidden = true;
          }
          if (tailDirty && network?.preferences)
            fillTailPreferences(network.preferences);
          tailDirty = false;
          tab = next;
          $("#rcRoot").dataset.tab = next;
          document.querySelectorAll("[data-rc-card]").forEach((card) => {
            card.hidden = next !== "status" && card.dataset.rcCard !== next;
          });
          $("#rcLAN").hidden = next !== "lan";
          $("#rcNetworkProxy").hidden = next !== "proxy";
          $("#rcNetwork").hidden = next !== "network";
          $("#rcNodeBaby").hidden = next !== "nodebaby";
          if (next === "nodebaby") RemoteHubNodeBaby.maybeCheck();
          $("#rcOverview").hidden = next !== "overview";

          document
            .querySelectorAll("[data-rc-tab]")
            .forEach((item) =>
              item.classList.toggle("active", item.dataset.rcTab === next),
            );
          if (next === "status") await Promise.all([RemoteHubLAN.refresh(), refreshProxySummary()]);
          if (next === "lan") await RemoteHubLAN.refresh();
          if (next === "proxy") await renderProxy();
          window.scrollTo?.(0, 0);
      });
    }
    document.querySelectorAll("[data-rc-open]").forEach((button) => {
      button.onclick = () => selectTab(button.dataset.rcOpen, button);
    });
    document.querySelectorAll("[data-rc-tab]").forEach((button) => {
      button.onclick = () => selectTab(button.dataset.rcTab, button);
    });
    $("#rcChangePassword").onclick = () => {
      $("#rcPasswordForm").reset();
      $("#rcPasswordError").hidden = true;
      $("#rcPasswordDialog").showModal();
    };
    $("#rcClosePassword").onclick = () => {
      if (!operation) $("#rcPasswordDialog").close();
    };
    $("#rcPasswordDialog").addEventListener("cancel", (event) => {
      if (operation) event.preventDefault();
    });
    $("#rcPasswordDialog").addEventListener("close", () =>
      $("#rcPasswordForm").reset(),
    );
    $("#rcPasswordForm").onsubmit = (event) => {
      event.preventDefault();
      busy($("#rcPasswordForm button[type=submit]"), async () => {
        if ($("#rcPassword").value !== $("#rcPasswordConfirm").value) {
          $("#rcPasswordError").textContent = "两次输入的密码不一致";
          $("#rcPasswordError").hidden = false;
          return;
        }
        try {
          await rdApi("/password", { password: $("#rcPassword").value });
          $("#rcPasswordDialog").close();
          notify("固定密码已更新");
          await refresh();
        } catch (error) {
          $("#rcPasswordError").textContent = error.message;
          $("#rcPasswordError").hidden = false;
        }
      });
    };
    $("#rcClearPassword").onclick = () =>
      busy($("#rcClearPassword"), async () => {
        if (
          !(await confirm(
            "清除固定密码",
            "清除后，使用固定密码的设备需要改用其他批准方式。",
          ))
        )
          return;
        await rdApi("/password", { password: "" });
        $("#rcPasswordDialog").close();
        notify("固定密码已清除");
        await refresh();
      });

    return { refresh, selectTab, settle: () => statusRequest || Promise.resolve() };
  }

  function summaryCard(target, glyph, title, statusId, addressId, detailId) {
    return `<article class="rc-summary" data-rc-card="${target}"><div class="rc-summary-head"><h2>${icon(glyph)}${title}</h2><span class="rc-dot" id="${statusId}">读取中</span></div><p id="${addressId}" class="mono">—</p><small ${detailId ? `id="${detailId}"` : ""} class="muted">${detailId ? "" : "本机远程桌面服务"}</small><button class="rc-summary-open" data-rc-open="${target}" aria-label="打开${title}">查看详情 ${icon("chevron")}</button></article>`;
  }
  function markup() {
    return `<div id="rcRoot" class="remote-connect" data-tab="status">
<div class="workspace-tabs rc-tabs" role="group" aria-label="网络连接管理"><button data-rc-tab="status" class="active">${icon("overview")}状态总览</button><button data-rc-tab="lan">${icon("network")}本地局域网</button><button data-rc-tab="network">${icon("network")}ORN</button><button data-rc-tab="nodebaby">${icon("link")}节点小宝</button><button data-rc-tab="proxy">${icon("settings")}网络代理</button><button data-rc-tab="overview">${icon("server")}RustDesk</button></div>
<div class="rc-summaries">
${summaryCard("lan", "network", "本地局域网", "rcLanState", "rcLanAddress", "rcLanSummary")}
${summaryCard("network", "network", "ORN", "rcTailState", "rcTailAddress", "rcTailCounts")}
${summaryCard("nodebaby", "link", "节点小宝", "nbState", "nbAddress", "nbSummary")}
${summaryCard("proxy", "settings", "网络代理", "rcProxyState", "rcProxyAddress", "rcProxySummary")}
${summaryCard("overview", "server", "RustDesk", "rcOnline", "rcNativeSummary", null)}
</div>
${RemoteHubLAN.markup()}
<section id="rcNetworkProxy" hidden></section>
${RemoteHubNodeBaby.markup()}
<section id="rcNetwork" hidden><div id="rcNetworkNotice" class="notice" hidden></div><div class="rc-tail-toolbar"><div class="rc-tail-actions"><button id="rcTailToggle" class="primary" disabled>读取状态…</button><button id="rcTailReconnect" disabled>${icon("refresh")}重新连接</button><button id="rcTailNetcheck" disabled>${icon("diagnose")}网络诊断</button><a id="rcTailLogin" class="button" target="_blank" rel="noopener" hidden>登录 ORN ${icon("external")}</a></div><a class="button" href="https://aaronchou313.github.io/open-remote-hub/" target="_blank" rel="noopener">设备目录 ${icon("external")}</a></div><p id="rcTailOperation" class="muted" hidden></p><p id="rcTailErrors" role="alert" class="rc-error" hidden></p>
<details class="rc-network-details"><summary>本机组网设置</summary><dl class="rc-tail-identity"><div><dt>设备名称</dt><dd id="rcTailHostname">—</dd></div><div><dt>MagicDNS</dt><dd id="rcTailDns" class="mono">—</dd></div><div><dt>组网</dt><dd id="rcTailNetwork">—</dd></div><div><dt>版本</dt><dd id="rcTailVersion">—</dd></div></dl><form id="rcTailSettings"><div class="rc-tail-preferences"><label class="switch-row"><span>使用组网 DNS</span><input type="checkbox" data-tail-option="accept-dns"></label><label class="switch-row"><span>接收子网路由</span><input type="checkbox" data-tail-option="accept-routes"></label><label class="switch-row"><span>拦截组网入站连接</span><input type="checkbox" data-tail-option="shields-up"></label><label class="switch-row"><span>使用出口节点时保留局域网访问</span><input type="checkbox" data-tail-option="exit-node-allow-lan-access"></label><label>出口节点<select id="rcExitNode" data-tail-option="exit-node"><option value="">不使用出口节点</option></select></label></div><div class="rc-form-actions"><span id="rcTailDirty" class="muted" hidden>尚未保存</span><button id="rcTailSave" type="submit" class="primary" disabled>保存组网设置</button></div></form></details>
<div class="rc-peer-toolbar"><input id="rcPeerSearch" type="search" aria-label="搜索组网设备" placeholder="搜索设备名称或组网地址"><label class="rc-online-filter"><input id="rcOnlyOnline" type="checkbox">仅在线设备</label></div><div id="rcPeerList" class="rc-peers"></div></section>
        <section id="rcOverview" hidden>
          <article class="panel rd-connection">
            <div class="section-heading"><h2>连接信息</h2><span id="rcVersion" class="version-label">—</span></div>
            <div class="rd-credentials">
              <div class="rd-credential">
                <label for="rcDeviceId">RustDesk ID</label>
                <div class="device-id-row"><input id="rcDeviceId" readonly value="—" aria-label="RustDesk ID"><button id="rcCopyId" class="icon-button" aria-label="复制 ID" title="复制 ID">${icon("copy")}</button></div>
              </div>
              <div class="rd-credential">
                <label for="rcTemporaryValue">临时密码</label>
                <div class="device-id-row"><input id="rcTemporaryValue" readonly autocomplete="off" aria-label="临时密码"><button id="rcCopyTemporary" class="icon-button" aria-label="复制临时密码" title="复制临时密码">${icon("copy")}</button></div>
              </div>
            </div>
            <div class="rd-connection-bottom">
              <dl class="rd-facts"><div><dt>接入服务</dt><dd id="rcAccepting">—</dd></div><div><dt>正在远程控制</dt><dd id="rcConnections">—</dd></div><div><dt>固定密码</dt><dd id="rcPasswordSet">—</dd></div><div><dt>进程</dt><dd id="rcProcesses" class="mono">—</dd></div></dl>
              <a id="rcConnectHere" class="button rd-open-client" href="#">${icon("external")}在当前设备的 RustDesk 中打开</a>
            </div>
            <div class="rd-runtime">
              <div class="rd-runtime-heading"><h3>运行管理</h3><button id="rcOpenNative" class="text-button">在主机打开客户端 ${icon("external")}</button></div>
              <div class="rd-runtime-controls">
                <label class="switch-row"><span>登录主机后自动运行</span><input id="rcAutostart" class="rd-toggle" type="checkbox" role="switch"></label>
                <div class="service-actions"><button id="rcServiceToggle">启动接入服务</button><button id="rcServiceRestart">重新连接接入服务</button></div>
              </div>
              <p id="rcNativeMessage" class="muted small" hidden></p>
            </div>
          </article>
          <form id="rcSettingsForm">
            <div class="rd-security-grid">
            <article class="panel rc-auth-panel">
              <h2>连接验证</h2>
              <label class="sr-only" for="rcApproveMode">连接批准方式</label>
              <select id="rcApproveMode" data-option="approve-mode" data-live-option>
                <option value="password">允许密码访问</option><option value="click">允许点击访问</option><option value="password-click">允许密码或点击访问</option>
              </select>
              <div id="rcPasswordOptions">
                <label class="rc-radio-row"><input type="radio" name="rcVerification" data-option="verification-method" data-live-option value="use-temporary-password">使用一次性密码</label>
                <fieldset id="rcTemporaryOptions" class="rc-password-length"><legend>一次性密码长度</legend>
                  ${["6","8","10"].map((length) => `<label><input type="radio" name="rcPasswordLength" data-option="temporary-password-length" data-live-option value="${length}">${length}</label>`).join("")}
                  <label class="rc-numeric-password"><input type="checkbox" data-option="allow-numeric-one-time-password" data-live-option>一次性密码为数字</label>
                </fieldset>
                <label class="rc-radio-row"><input type="radio" name="rcVerification" data-option="verification-method" data-live-option value="use-permanent-password">使用固定密码</label>
                <button id="rcChangePassword" type="button" class="rc-set-password">${icon("password")}设置固定密码</button>
                <label class="rc-radio-row"><input type="radio" name="rcVerification" data-option="verification-method" data-live-option value="use-both-passwords">同时使用两种密码</label>
              </div>
            </article>
            <article class="panel rc-permission-panel"><h2>权限</h2><div class="field-grid">
              ${[["enable-keyboard","键盘与鼠标"],["enable-clipboard","剪贴板同步"],["enable-file-transfer","文件传输"],["enable-audio","音频"],["allow-remote-config-modification","允许远程修改配置"]].map(([key,label]) => `<label class="switch-row"><span>${label}</span><input type="checkbox" class="rd-toggle" role="switch" data-option="${key}" data-live-option></label>`).join("")}
            </div></article>
            </div>
            <details class="panel rc-network-details rd-network"><summary>网络设置 ${icon("chevron")}</summary><div class="field-grid">
              <label>ID 服务器<input data-option="custom-rendezvous-server" placeholder="RustDesk 公共服务" autocomplete="off"></label>
              <label>中继服务器<input data-option="relay-server" autocomplete="off"></label>
              <label>API 服务器<input data-option="api-server" autocomplete="off"></label>
              <label>服务器公钥<input data-option="key" autocomplete="off"></label>
              <label class="switch-row"><span>允许 IP 直连</span><input type="checkbox" data-option="direct-server" data-live-option></label>
              <label>直连端口<input data-option="direct-access-port" type="number" min="1" max="65535"></label>
            </div><div class="rc-form-actions"><span id="rcDirty" class="muted" hidden>尚未保存</span><button id="rcSaveSettings" type="submit" class="primary">保存网络设置</button></div></details>
          </form>
        </section>
    <dialog id="rcPasswordDialog" aria-labelledby="rcPasswordTitle">
      <form id="rcPasswordForm">
        <div class="section-heading">
          <h2 id="rcPasswordTitle">设置固定密码</h2>
          <button
            type="button"
            id="rcClosePassword"
            class="icon-button"
            aria-label="关闭"
          >
            <svg><use href="/static/icons.svg#x"></use></svg>
          </button>
        </div>
        <label for="rcPassword">新密码</label
        ><input
          id="rcPassword"
          type="password"
          autocomplete="new-password"
          required
        /><label for="rcPasswordConfirm">再次输入</label
        ><input
          id="rcPasswordConfirm"
          type="password"
          autocomplete="new-password"
          required
        />
        <p id="rcPasswordError" role="alert" hidden></p>
        <div class="dialog-actions">
          <button id="rcClearPassword" type="button" class="danger">
            清除固定密码</button
          ><button type="submit" class="primary">保存密码</button>
        </div>
      </form>
    </dialog>
  
</div>`;
  }

  let controller;

  function fillTailPreferences(preferences) {
    tailOriginal = preferences;
    document.querySelectorAll("[data-tail-option]").forEach((input) => {
      const value = preferences[input.dataset.tailOption];
      if (input.type === "checkbox") input.checked = value === true;
      else input.value = value || "";
      input.disabled = false;
    });
    tailDirty = false;
    $("#rcTailDirty").hidden = true;
  }

  function tailChanges() {
    const changes = {};
    document.querySelectorAll("[data-tail-option]").forEach((input) => {
      const value = input.type === "checkbox" ? input.checked : input.value;
      if (value !== tailOriginal[input.dataset.tailOption])
        changes[input.dataset.tailOption] = value;
    });
    return changes;
  }

  function fallbackNotice(message) {
    expectedDisconnect = true;
    $("#rcNetworkNotice").innerHTML =
      `<p>${esc(message)}</p>${lanUrls.map((url) => `<a class="button" href="${esc(url)}">使用局域网入口 ${icon("external")}</a>`).join("")}`;
    $("#rcNetworkNotice").hidden = false;
  }

  function updateNetwork(value, urls) {
    network = value;
    lanUrls = urls;
    const connected = value.state === "Running";
    if (connected && value.last_operation?.state !== "pending") {
      expectedDisconnect = false;
      $("#rcNetworkNotice").hidden = true;
    }
    const labels = {
      Running: "已连接",
      Stopped: "已断开",
      NeedsLogin: "需要登录",
      NeedsMachineAuth: "等待设备批准",
      Starting: "正在连接",
      NoState: "正在初始化",
    };
    $("#rcTailState").textContent = !value.available
      ? "未安装"
      : !value.reachable
        ? "不可用"
        : labels[value.state] || value.state || "未知";
    $("#rcTailState").classList.toggle("online", connected);
    $("#rcTailAddress").textContent =
      value.device?.addresses?.join(" · ") || "—";
    $("#rcTailCounts").textContent = connected
      ? `${value.peers.filter((peer) => peer.online).length} / ${value.peers.length} 台其他设备在线`
      : "当前未连接组网";
    $("#rcNativeSummary").textContent = state?.ready
      ? `${state.device_id} · ${state.connections ?? 0} 个远程连接`
      : state?.message || "客户端未就绪";
    $("#rcTailHostname").textContent = value.device?.hostname || "—";
    $("#rcTailDns").textContent = value.device?.dns || "—";
    $("#rcTailVersion").textContent = value.version || "—";
    $("#rcTailNetwork").textContent = value.network || "—";
    $("#rcTailErrors").textContent = [
      value.error,
      value.preference_error,
      ...(value.health || []),
    ]
      .filter(Boolean)
      .join("\n");
    $("#rcTailErrors").hidden = !$("#rcTailErrors").textContent;
    $("#rcTailToggle").textContent = connected ? "断开组网" : "连接组网";
    $("#rcTailNetcheck").disabled = !value.available;
    $("#rcTailToggle").disabled =
      !value.available || value.last_operation?.state === "pending";
    $("#rcTailReconnect").disabled =
      !value.available || value.last_operation?.state === "pending";
    $("#rcTailLogin").href = value.auth_url || "#";
    $("#rcTailLogin").hidden = !value.auth_url;
    const exit = $("#rcExitNode");
    const selected = tailDirty
      ? exit.value
      : value.preferences?.["exit-node"] || "";
    const options = value.peers
      .filter((peer) => peer.exit_node_available)
      .map((peer) => ({
        name: peer.hostname || peer.dns,
        ip: peer.addresses.find((ip) => !ip.includes(":")) || peer.addresses[0],
      }));
    exit.innerHTML =
      '<option value="">不使用出口节点</option>' +
      options
        .map(
          (item) =>
            `<option value="${esc(item.ip)}">${esc(item.name)} · ${esc(item.ip)}</option>`,
        )
        .join("");
    if (selected && !options.some((item) => item.ip === selected))
      exit.insertAdjacentHTML(
        "beforeend",
        `<option value="${esc(selected)}">${esc(selected)} · 已选择</option>`,
      );
    exit.value = selected;
    $("#rcTailSettings").hidden = value.backend === "orn";
    $("#rcTailSave").disabled = !value.preferences;
    if (value.preferences && !tailDirty) fillTailPreferences(value.preferences);
    if (!value.preferences)
      document.querySelectorAll("[data-tail-option]").forEach((input) => {
        input.disabled = true;
      });
    const last = value.last_operation;
    $("#rcTailOperation").textContent =
      last?.state === "pending"
        ? "正在执行组网操作…"
        : last?.state === "error"
          ? last.message
          : "";
    $("#rcTailOperation").hidden = !$("#rcTailOperation").textContent;
    drawPeers();
  }

  function drawPeers() {
    if (network?.state !== "Running") {
      $("#rcPeerList").innerHTML = empty("组网连接后显示设备状态");
      return;
    }
    const rows = (network?.peers || []).filter(
      (peer) =>
        (!onlyOnline || peer.online) &&
        `${peer.hostname} ${peer.dns} ${peer.addresses.join(" ")}`
          .toLowerCase()
          .includes(query.toLowerCase()),
    );
    $("#rcPeerList").innerHTML = rows.length
      ? table(
          ["设备", "组网地址", "连接状态", "累计收发", "操作"],
          rows.map(
            (peer) =>
              `<tr><td><strong>${esc(peer.hostname === "localhost" && peer.dns ? peer.dns.split(".")[0] : peer.hostname || peer.dns || "未命名设备")}</strong><small>${esc(peer.os)}</small></td><td class="mono">${peer.addresses.map((address) => `<span>${esc(address)}</span>`).join("")}</td><td><span class="rc-dot ${peer.online ? "online" : ""}">${peer.online ? "在线" : "离线"}</span><small>${peer.online ? (peer.route === "direct" ? "直连" : peer.route === "relay" ? "中继 · " + esc(peer.relay) : "按需建立连接") : peer.last_seen && !peer.last_seen.startsWith("0001") ? "上次在线 " + new Date(peer.last_seen).toLocaleString() : "暂无近期连接"}</small></td><td><small>↑ ${bytes(peer.tx)}</small><small>↓ ${bytes(peer.rx)}</small></td><td><div class="rc-peer-actions"><button data-peer-ping="${esc(peer.id)}">${icon("diagnose")}检测</button><button data-peer-copy="${esc(peer.id)}">${icon("copy")}复制 IP</button></div></td></tr>`,
          ),
        )
      : empty(
          query || onlyOnline ? "没有匹配的组网设备" : "当前组网中没有其他设备",
        );
    document.querySelectorAll("[data-peer-ping]").forEach(
      (button) =>
        (button.onclick = () =>
          busy(button, async () => {
            const node = network.peers.find(
              (peer) => peer.id === button.dataset.peerPing,
            );
            const result = await api("/remote-connect/tailscale/ping", {
              id: node.id,
            });
            if (current())
              output("ORN · " + node.hostname, result.output);
          })),
    );
    document.querySelectorAll("[data-peer-copy]").forEach(
      (button) =>
        (button.onclick = () =>
          busy(button, async () => {
            const node = network.peers.find(
              (peer) => peer.id === button.dataset.peerCopy,
            );
            await copy(
              node.addresses.find((address) => !address.includes(":")) ||
                node.addresses[0],
            );
            notify("组网 IP 已复制");
          })),
    );
  }

  function bindNetwork() {
    $("#rcPeerSearch").oninput = (event) => {
      query = event.target.value;
      drawPeers();
    };
    $("#rcOnlyOnline").onchange = (event) => {
      onlyOnline = event.target.checked;
      drawPeers();
    };
    $("#rcTailSettings").onchange = () => {
      tailDirty = Object.keys(tailChanges()).length > 0;
      $("#rcTailDirty").hidden = !tailDirty;
    };
    $("#rcTailSettings").onsubmit = (event) => {
      event.preventDefault();
      busy($("#rcTailSave"), async () => {
        const changes = tailChanges();
        const disruptive =
          changes["shields-up"] === true ||
          "exit-node" in changes ||
          "exit-node-allow-lan-access" in changes;
        if (
          disruptive &&
          !(await confirm(
            "更改组网连接设置",
            "入站拦截或出口路由更改可能中断当前远程访问。请确认已准备好局域网访问方式。",
          ))
        )
          return;
        if (disruptive)
          fallbackNotice(
            "正在应用组网设置。连接中断时可从局域网入口继续管理。",
          );
        const controls = [
          ...$("#rcTailSettings").querySelectorAll("input,select,button"),
        ];
        controls.forEach((control) => {
          control.disabled = true;
        });
        try {
          const result = await api("/remote-connect/tailscale/settings", {
            changes,
            before: tailOriginal,
            confirm: disruptive,
          });
          fillTailPreferences(result.preferences);
          expectedDisconnect = false;
          notify("组网设置已保存");
          await controller.refresh();
        } catch (error) {
          if (!disruptive || error.status) {
            expectedDisconnect = false;
            $("#rcNetworkNotice").hidden = true;
            throw error;
          }
          notify("请从可用的网络入口刷新，核对组网设置结果");
        } finally {
          controls.forEach((control) => {
            control.disabled = false;
          });
        }
      });
    };
    async function control(action, button) {
      await busy(button, async () => {
        if (
          action !== "connect" &&
          !(await confirm(
            action === "disconnect" ? "断开 ORN" : "重新连接 ORN",
            "当前通过 ORN 建立的控制台和远程桌面连接将中断。可通过局域网入口继续管理。",
          ))
        )
          return;
        await api("/remote-connect/tailscale/control", {
          action,
          confirm: action !== "connect",
        });
        if (action !== "connect")
          fallbackNotice(
            "组网操作请求已发送。当前入口断开后，请使用局域网入口查看执行结果。",
          );
        else notify("已请求连接 ORN");
        if (action === "connect") await controller.refresh();
      });
    }
    $("#rcTailToggle").onclick = () =>
      control(
        network?.state === "Running" ? "disconnect" : "connect",
        $("#rcTailToggle"),
      );
    $("#rcTailReconnect").onclick = () =>
      control("reconnect", $("#rcTailReconnect"));
    $("#rcTailNetcheck").onclick = () =>
      busy($("#rcTailNetcheck"), async () => {
        const result = await api("/remote-connect/tailscale/netcheck", {});
        if (current()) output("ORN 网络诊断", result.output);
      });
  }

  async function render(check) {
    current = check;
    if (!$("#rcRoot")) {
      tab = "status";
      original = {};
      effectiveOriginal = {};
      dirty = false;
      tailDirty = false;
      expectedDisconnect = false;
      $("#content").innerHTML = markup();
      controller = bindRustdesk();
      bindNetwork();
      RemoteHubLAN.mount({copy, current: () => current()});
      RemoteHubNodeBaby.mount({busy, copy, current: () => current(), refresh: () => controller.refresh()});
      window.scrollTo?.(0, 0);
    }
    if (!operation) await controller.refresh();
    if (requestedTab) {
      const next = requestedTab;
      requestedTab = null;
      await controller.selectTab(next, document.querySelector(`[data-rc-tab="${next}"]`));
    } else if (tab === "proxy") await renderProxy();
  }
  async function canLeave() {
    if (operation) return false;
    if (
      (dirty || tailDirty) &&
      !(await confirm("放弃未保存的修改", "离开页面将丢弃尚未保存的设置。"))
    )
      return false;
    dirty = false;
    tailDirty = false;
    return true;
  }
  function reset() {
    current = () => false;
    dirty = false;
    tailDirty = false;
    original = {};
    effectiveOriginal = {};
    tailOriginal = {};
    RemoteHubLAN.reset();
    proxyVersion++;
    RemoteHubNodeBaby.reset();
    state = null;
    network = null;
    document
      .querySelectorAll(".remote-connect dialog[open]")
      .forEach((dialog) => dialog.close());
    const password = $("#rcPasswordForm");
    if (password) password.reset();
    const temporary = $("#rcTemporaryValue");
    if (temporary) temporary.value = "";
  }
  setInterval(() => {
    if (
      current() &&
      !document.hidden &&
      !operation &&
      tab !== "proxy" &&
      !document.querySelector(".remote-connect dialog[open]") &&
      !$("#outputDialog").open &&
      !$("#confirmDialog").open
    ) {
      controller.refresh().catch((error) => {
        if (current() && !expectedDisconnect) showError(error, false);
      });
    }
  }, 5000);
  window.addEventListener("beforeunload", (event) => {
    if (current() && (dirty || tailDirty)) {
      event.preventDefault();
      event.returnValue = "";
    }
  });
  return {
    render,
    openTab: (next) => { requestedTab = next; },
    canLeave,
    reset,
    isOpen: () =>
      Boolean(document.querySelector(".remote-connect dialog[open]")),
  };
})();
