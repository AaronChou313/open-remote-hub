"use strict";
window.RemoteHubRemoteConnect = (() => {
  const $ = (selector) => document.querySelector(selector);
  let current = () => false;
  let state;
  let original = {};
  let tab = "network";
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
      $("#rcTemporaryPassword").disabled = !value.ready;
      $("#rcNativeMessage").textContent = value.message || "";
      $("#rcNativeMessage").hidden = !value.message;
    }
    async function refresh() {
      if (statusRequest) return statusRequest;
      const owner = current;
      const request = api("/remote-connect").then((data) => {
        if (!owner()) return;
        updateStatus(data.rustdesk);
        updateNetwork(data.tailscale, data.lan_urls);
        $("#updated").textContent = "更新于 " + new Date().toLocaleTimeString();
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
    $("#rcConnectForm").onsubmit = (event) => {
      event.preventDefault();
      busy($("#rcConnectForm button[type=submit]"), async () => {
        await rdApi("/connect", {
          target: $("#rcTarget").value,
          mode: $("#rcMode").value,
        });
        notify("连接请求已发送到主机");
      });
    };
    $("#rcTemporaryPassword").onclick = () =>
      busy($("#rcTemporaryPassword"), async () => {
        const result = await rdApi("/password/temporary", {});
        $("#rcTemporaryValue").value = result.password || "";
        $("#rcTemporaryDialog").showModal();
      });
    $("#rcCloseTemporary").onclick = () => $("#rcTemporaryDialog").close();
    $("#rcTemporaryDialog").addEventListener("close", () => {
      $("#rcTemporaryValue").value = "";
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
            if (input.checked !== normalized(key, original[key]))
              result[key] = input.checked ? "Y" : "N";
          } else if (input.value.trim() !== original[key])
            result[key] = input.value.trim();
        });
      return result;
    }
    function markDirty() {
      dirty = Object.keys(changes()).length > 0;
      $("#rcDirty").hidden = !dirty;
    }
    function fillSettings(options) {
      original = options;
      document
        .querySelectorAll(".remote-connect [data-option]")
        .forEach((input) => {
          const key = input.dataset.option;
          if (input.type === "checkbox")
            input.checked = normalized(key, options[key]);
          else input.value = options[key] || "";
        });
      markDirty();
    }
    async function loadSettings() {
      loadingSettings = true;
      $("#rcSaveSettings").disabled = true;
      try {
        const result = await rdApi("/settings");
        fillSettings(result.options);
      } finally {
        loadingSettings = false;
        $("#rcSaveSettings").disabled = false;
      }
    }
    $("#rcSettingsForm").oninput = () => {
      if (!loadingSettings) markDirty();
    };
    $("#rcSettingsForm").onchange = () => {
      if (!loadingSettings) markDirty();
    };
    $("#rcSettingsForm").onsubmit = (event) => {
      event.preventDefault();
      busy($("#rcSaveSettings"), async () => {
        const patch = changes();
        const controls = [
          ...$("#rcSettingsForm").querySelectorAll("input,select,button"),
        ];
        controls.forEach((control) => (control.disabled = true));
        try {
          const result = await rdApi("/settings", {
            changes: patch,
            before: original,
          });
          fillSettings(result.options);
          notify("设置已保存");
          await refresh();
        } finally {
          controls.forEach((control) => (control.disabled = false));
        }
      });
    };
    document.querySelectorAll("[data-rc-tab]").forEach((button) => {
      button.onclick = () =>
        busy(button, async () => {
          const next = button.dataset.rcTab;
          if (next === tab) return;
          if (
            (dirty || tailDirty) &&
            !(await confirm(
              "放弃未保存的修改",
              "离开设置将丢弃本次尚未保存的修改。",
            ))
          )
            return;
          if (next === "settings") await loadSettings();
          else {
            dirty = false;
            $("#rcDirty").hidden = true;
          }
          if (tailDirty && network?.preferences)
            fillTailPreferences(network.preferences);
          tailDirty = false;
          tab = next;
          $("#rcNetwork").hidden = next !== "network";
          $("#rcOverview").hidden = next !== "overview";
          $("#rcSettings").hidden = next !== "settings";
          document
            .querySelectorAll("[data-rc-tab]")
            .forEach((item) =>
              item.classList.toggle("active", item.dataset.rcTab === next),
            );
          window.scrollTo?.(0, 0);
        });
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

    return { refresh, settle: () => statusRequest || Promise.resolve() };
  }

  function markup() {
    return `<div id="rcRoot" class="remote-connect">
<div class="rc-summaries"><article class="rc-summary"><div class="rc-summary-head"><h2>${icon("network")}Tailscale</h2><span class="rc-dot" id="rcTailState">读取中</span></div><p id="rcTailAddress" class="mono">—</p><small id="rcTailCounts" class="muted"></small></article><article class="rc-summary"><div class="rc-summary-head"><h2>${icon("server")}RustDesk</h2><span class="rc-dot" id="rcOnline">读取中</span></div><p id="rcNativeSummary" class="mono">—</p><small class="muted">本机远程桌面服务</small></article></div>
<div class="workspace-tabs rc-tabs" role="group" aria-label="远程连接管理"><button data-rc-tab="network" class="active">${icon("network")}组网设备</button><button data-rc-tab="overview">${icon("server")}RustDesk</button><button data-rc-tab="settings">${icon("settings")}RustDesk 设置</button></div>
<section id="rcNetwork"><div id="rcNetworkNotice" class="notice" hidden></div><div class="rc-tail-toolbar"><div class="rc-tail-actions"><button id="rcTailToggle" class="primary" disabled>读取状态…</button><button id="rcTailReconnect" disabled>${icon("refresh")}重新连接</button><button id="rcTailNetcheck" disabled>${icon("diagnose")}网络诊断</button><a id="rcTailLogin" class="button" target="_blank" rel="noopener" hidden>登录 Tailscale ${icon("external")}</a></div><a class="button" href="https://login.tailscale.com/admin/machines" target="_blank" rel="noopener">组网管理后台 ${icon("external")}</a></div><p id="rcTailOperation" class="muted" hidden></p><p id="rcTailErrors" role="alert" class="rc-error" hidden></p>
<details class="rc-network-details"><summary>本机组网设置</summary><dl class="rc-tail-identity"><div><dt>设备名称</dt><dd id="rcTailHostname">—</dd></div><div><dt>MagicDNS</dt><dd id="rcTailDns" class="mono">—</dd></div><div><dt>组网</dt><dd id="rcTailNetwork">—</dd></div><div><dt>版本</dt><dd id="rcTailVersion">—</dd></div></dl><form id="rcTailSettings"><div class="rc-tail-preferences"><label class="switch-row"><span>使用组网 DNS</span><input type="checkbox" data-tail-option="accept-dns"></label><label class="switch-row"><span>接收子网路由</span><input type="checkbox" data-tail-option="accept-routes"></label><label class="switch-row"><span>拦截组网入站连接</span><input type="checkbox" data-tail-option="shields-up"></label><label class="switch-row"><span>使用出口节点时保留局域网访问</span><input type="checkbox" data-tail-option="exit-node-allow-lan-access"></label><label>出口节点<select id="rcExitNode" data-tail-option="exit-node"><option value="">不使用出口节点</option></select></label></div><div class="rc-form-actions"><span id="rcTailDirty" class="muted" hidden>尚未保存</span><button id="rcTailSave" type="submit" class="primary" disabled>保存组网设置</button></div></form></details>
<div class="rc-peer-toolbar"><input id="rcPeerSearch" type="search" aria-label="搜索组网设备" placeholder="搜索设备名称或组网地址"><label class="rc-online-filter"><input id="rcOnlyOnline" type="checkbox">仅在线设备</label></div><div id="rcPeerList" class="rc-peers"></div></section>
<section id="rcOverview" hidden>
          <div class="overview-grid">
            <article class="panel device">
              <div class="section-heading">
                <h2>RustDesk 客户端</h2>
                <span class="muted" id="rcVersion">—</span>
              </div>
              <label class="muted" for="rcDeviceId">RustDesk ID</label>
              <div class="device-id-row">
                <input
                  id="rcDeviceId"
                  readonly
                  value="—"
                  aria-label="RustDesk ID"
                /><button
                  id="rcCopyId"
                  class="icon-button"
                  aria-label="复制 ID"
                  title="复制 ID"
                >
                  <svg><use href="/static/icons.svg#copy"></use></svg>
                </button>
              </div>
              <div class="device-actions">
                <a id="rcConnectHere" class="button primary" href="#"
                  ><svg><use href="/static/icons.svg#external-link"></use></svg
                  >从当前设备连接此主机</a
                ><button id="rcTemporaryPassword">
                  <svg><use href="/static/icons.svg#key-round"></use></svg>查看临时密码
                </button>
              </div>
              <dl>
                <div>
                  <dt>接入服务</dt>
                  <dd id="rcAccepting">—</dd>
                </div>
                <div>
                  <dt>正在远程控制</dt>
                  <dd id="rcConnections">—</dd>
                </div>
                <div>
                  <dt>固定密码</dt>
                  <dd id="rcPasswordSet">—</dd>
                </div>
                <div>
                  <dt>进程</dt>
                  <dd id="rcProcesses" class="mono">—</dd>
                </div>
              </dl>
            </article>
            <div class="right-column">
              <article class="panel">
                <div class="section-heading">
                  <h2>在主机上发起连接</h2>
                  <svg class="section-icon">
                    <use href="/static/icons.svg#terminal"></use>
                  </svg>
                </div>
                <form id="rcConnectForm">
                  <label for="rcTarget">目标 ID 或主机地址</label
                  ><input
                    id="rcTarget"
                    name="target"
                    autocomplete="off"
                    placeholder="输入对方的 RustDesk ID"
                    required
                    maxlength="254"
                  />
                  <div class="connect-bottom">
                    <label class="mode-select" for="rcMode"
                      ><span class="sr-only">连接方式</span
                      ><select id="rcMode">
                        <option value="desktop">远程桌面</option>
                        <option value="files">文件传输</option>
                      </select></label
                    ><button type="submit" class="primary">
                      <svg><use href="/static/icons.svg#play"></use></svg>在主机上连接
                    </button>
                  </div>
                </form>
                <p class="muted small">
                  连接窗口显示在主机桌面，密码和确认由 RustDesk 处理。
                </p>
              </article>
              <article class="panel">
                <div class="section-heading">
                  <h2>运行管理</h2>
                  <button id="rcOpenNative" class="text-button">
                    在主机打开客户端<svg>
                      <use href="/static/icons.svg#external-link"></use>
                    </svg>
                  </button>
                </div>
                <label class="switch-row" for="rcAutostart"
                  ><span>登录主机后自动运行</span
                  ><input id="rcAutostart" type="checkbox" role="switch"
                /></label>
                <div class="service-actions">
                  <button id="rcServiceToggle" class="primary">
                    启动接入服务</button
                  ><button id="rcServiceRestart">重新连接接入服务</button>
                </div>
                <p id="rcNativeMessage" class="muted small" hidden></p>
              </article>
            </div>
          </div>
        </section>
        <section id="rcSettings" hidden>
          <form id="rcSettingsForm">
            <div class="settings-heading">
              <h2>客户端设置</h2>
              <div class="actions">
                <span id="rcDirty" class="muted small" hidden>尚未保存</span
                ><button id="rcSaveSettings" type="submit" class="primary">
                  保存设置
                </button>
              </div>
            </div>
            <div class="settings-section">
              <div><h3>连接与网络</h3></div>
              <div class="field-grid">
                <label
                  >ID 服务器<input
                    data-option="custom-rendezvous-server"
                    placeholder="默认使用 RustDesk 公共服务"
                    autocomplete="off" /></label
                ><label
                  >中继服务器<input
                    data-option="relay-server"
                    placeholder="可选，主机名或 IP"
                    autocomplete="off" /></label
                ><label
                  >API 服务器<input
                    data-option="api-server"
                    placeholder="可选，http:// 或 https://"
                    autocomplete="off" /></label
                ><label
                  >服务器公钥<input
                    data-option="key"
                    placeholder="自建服务器的公钥"
                    autocomplete="off" /></label
                ><label class="switch-row"
                  ><span>允许 IP 直连</span
                  ><input type="checkbox" data-option="direct-server" /></label
                ><label
                  >直连端口<input
                    data-option="direct-access-port"
                    type="number"
                    min="1"
                    max="65535"
                    placeholder="21118"
                /></label>
              </div>
            </div>
            <div class="settings-section">
              <h3>操作权限</h3>
              <div class="field-grid">
                <label class="switch-row"
                  ><span>键盘与鼠标</span
                  ><input
                    type="checkbox"
                    data-option="enable-keyboard" /></label
                ><label class="switch-row"
                  ><span>剪贴板同步</span
                  ><input
                    type="checkbox"
                    data-option="enable-clipboard" /></label
                ><label class="switch-row"
                  ><span>文件传输</span
                  ><input
                    type="checkbox"
                    data-option="enable-file-transfer" /></label
                ><label class="switch-row"
                  ><span>音频</span
                  ><input type="checkbox" data-option="enable-audio"
                /></label>
              </div>
            </div>
            <div class="settings-section">
              <h3>连接验证</h3>
              <div class="field-grid">
                <label
                  >批准方式<select data-option="approve-mode">
                    <option value="">沿用原生默认设置</option>
                    <option value="password">密码批准</option>
                    <option value="click">手动确认</option>
                    <option value="password-click">密码或手动确认</option>
                  </select></label
                ><label
                  >访问密码<select data-option="verification-method">
                    <option value="">沿用原生默认设置</option>
                    <option value="use-temporary-password">临时密码</option>
                    <option value="use-permanent-password">固定密码</option>
                    <option value="use-both-passwords">
                      临时密码与固定密码
                    </option>
                  </select></label
                ><label
                  >临时密码长度<select data-option="temporary-password-length">
                    <option value="">沿用原生默认设置</option>
                    <option value="6">6 位</option>
                    <option value="8">8 位</option>
                    <option value="10">10 位</option>
                  </select></label
                >
                <div class="password-setting">
                  <span>固定密码</span
                  ><button id="rcChangePassword" type="button">
                    <svg><use href="/static/icons.svg#key-round"></use></svg
                    >设置固定密码
                  </button>
                </div>
              </div>
            </div>
          </form>
        </section><dialog id="rcTemporaryDialog" aria-labelledby="rcTemporaryTitle">
      <div class="section-heading">
        <h2 id="rcTemporaryTitle">临时访问密码</h2>
        <button id="rcCloseTemporary" class="icon-button" aria-label="关闭">
          <svg><use href="/static/icons.svg#x"></use></svg>
        </button>
      </div>
      <input
        id="rcTemporaryValue"
        readonly
        aria-label="临时访问密码"
        class="mono"
      />
      <div class="dialog-actions">
        <button id="rcCopyTemporary" class="primary">复制密码</button>
      </div>
    </dialog>
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
              output("Tailscale · " + node.hostname, result.output);
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
            action === "disconnect" ? "断开 Tailscale" : "重新连接 Tailscale",
            "当前通过 Tailscale 建立的控制台和远程桌面连接将中断。可通过局域网入口继续管理。",
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
        else notify("已请求连接 Tailscale");
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
        if (current()) output("Tailscale 网络诊断", result.output);
      });
  }

  async function render(check) {
    current = check;
    if (!$("#rcRoot")) {
      tab = "network";
      dirty = false;
      tailDirty = false;
      expectedDisconnect = false;
      $("#content").innerHTML = markup();
      controller = bindRustdesk();
      bindNetwork();
      window.scrollTo?.(0, 0);
    }
    if (!operation) await controller.refresh();
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
    tailOriginal = {};
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
    canLeave,
    reset,
    isOpen: () =>
      Boolean(document.querySelector(".remote-connect dialog[open]")),
  };
})();
