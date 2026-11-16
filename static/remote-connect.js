"use strict";
window.RemoteHubRemoteConnect = (() => {
  const $ = (selector) => document.querySelector(selector);
  let current = () => false;
  let state;
  let original = {};
  let effectiveOriginal = {};
  let operation = false;
  let dirty = false;
  let loadingSettings = false;
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
  const copy = value => copyText(value);
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
      const host = location.hostname;
      const port = original["direct-access-port"] || "21118";
      $("#rcConnectHere").href = "rustdesk://connection/new/" + ((host.includes(":") ? "[" + host + "]" : host) + ":" + port);
      $("#rcConnectHere").setAttribute("aria-disabled", String(!value.ready));
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
      const request = rdApi("").then((data) => {
        if (!owner()) return;
        updateStatus(data);
        $("#updated").textContent = "更新于 " + new Date().toLocaleTimeString();
        if (data.ready) return loadSettings();
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
      event.preventDefault();
      if (!state?.ready) return;
      busy($("#rcConnectHere"), async () => {
        const target = RemoteHubApplications.meshGateway()
          ? await RemoteHubApplications.openService("desktop", "") : $("#rcConnectHere").href;
        if (!RemoteHubApplications.nativeOpen(target)) location.assign(target);
      });
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
    return `<div id="rcRoot" class="remote-connect" data-tab="overview"><section id="rcOverview">
          <article class="panel rd-connection">
            <div class="section-heading"><h2>连接信息</h2><span id="rcOnline" class="badge">—</span><span id="rcVersion" class="version-label">—</span></div>
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
            <p class="muted small">当前设备需先<a href="https://rustdesk.com/download" target="_blank" rel="noopener">安装 RustDesk</a>。被控 Mac 还需在系统设置中授权屏幕录制和辅助功能。</p>
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

  async function render(check) {
    current = check;
    if (!$("#rcRoot")) {
      original = {};
      effectiveOriginal = {};
      dirty = false;
      $("#content").innerHTML = markup();
      controller = bindRustdesk();
    }
    if (!operation) await controller.refresh();
  }
  async function canLeave() {
    if (operation) return false;
    if (
      dirty &&
      !(await confirm("放弃未保存的修改", "离开页面将丢弃尚未保存的设置。"))
    )
      return false;
    dirty = false;
    return true;
  }
  function reset() {
    current = () => false;
    dirty = false;
    original = {};
    effectiveOriginal = {};
    state = null;
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
        if (current()) showError(error, false);
      });
    }
  }, 5000);
  window.addEventListener("beforeunload", (event) => {
    if (current() && dirty) {
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
