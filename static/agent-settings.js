'use strict';
window.RemoteHubAgentSettings = (() => {
  let dirty = false;
  const esc = value => RemoteHubFormControls.escape(value);
  async function render(check, target, api) {
    if (dirty && document.querySelector('#agentAccessForm')) return;
    const data = await api('/agent/settings');
    if (!check()) return;
    const $ = selector => document.querySelector(selector);
    const mode = data.bind === '127.0.0.1' ? 'local' : data.bind === '0.0.0.0' ? 'network' : 'custom';
    $(target).innerHTML = `<section class="settings-section"><h2>Web 控制台访问</h2><form id="agentAccessForm" class="agent-access-form"><label>访问范围<select id="agentAccessMode"><option value="local" ${mode==='local'?'selected':''}>仅本机与 ORH 私网</option><option value="network" ${mode==='network'?'selected':''}>允许局域网和备用网络</option><option value="custom" ${mode==='custom'?'selected':''}>指定本机网络地址</option></select></label><label id="agentBindField" ${mode==='custom'?'':'hidden'}>监听地址<input id="agentBindAddress" value="${esc(data.bind)}" placeholder="例如 192.168.1.20"></label><fieldset><legend>允许访问的设备地址</legend><p class="muted">添加目标电脑的局域网、Tailscale 或节点小宝 IP。本机和 ORH 私网入口自动保留。</p><div id="agentAllowedHosts"></div></fieldset><fieldset><legend>离线恢复登录</legend><label class="switch-row"><span>启用独立本地恢复密码</span><input id="agentRecovery" type="checkbox" role="switch" ${data.recovery_enabled?'checked':''}></label><label>恢复密码<input id="agentRecoveryPassword" type="password" autocomplete="new-password" minlength="8" placeholder="${data.recovery_enabled?'输入新密码可更换现有密码':'至少 8 个字符'}"></label><p class="muted">Cloud 不可用时可在目标 Web 控制台使用此密码登录。</p></fieldset><p id="agentAccessError" role="alert" class="detail-error"></p><p id="agentAccessNotice" role="status">${esc((data.listener_errors||[]).join(' · ')) || (data.restart_required?'访问设置已保存，重启后台后生效。':'')}</p><div class="toolbar"><button id="agentAccessSave" type="submit" class="primary">保存访问设置</button>${data.restart_required&&data.restart_supported?'<button id="agentRestart" type="button">重启后台并应用</button>':''}</div></form>${data.urls.length?`<h3>可用访问地址</h3><div class="agent-access-urls">${data.urls.map(url=>`<a class="button" href="${esc(url)}" target="_blank" rel="noopener">${esc(url)}</a>`).join('')}</div>`:''}<details class="settings-help"><summary>备用网络访问</summary><p>Tailscale、节点小宝由其客户端管理。可通过已允许的地址访问 Web 控制台、SSH 和 RustDesk。</p><a class="button" href="#lan">查看本机局域网</a></details></section>`;
    const addresses = RemoteHubFormControls.list('#agentAllowedHosts',data.allowed_hosts,{label:'地址',placeholder:'IP 或设备名称',onChange:()=>{dirty=true;}});
    $('#agentAccessMode').onchange = () => { $('#agentBindField').hidden = $('#agentAccessMode').value !== 'custom'; dirty=true; };
    $('#agentAccessForm').oninput = () => {dirty=true;};
    $('#agentAccessForm').onsubmit = async event => {
      event.preventDefault(); const button=$('#agentAccessSave'); button.disabled=true;
      try {
        const selected=$('#agentAccessMode').value;
        await api('/agent/settings',{bind:selected==='local'?'127.0.0.1':selected==='network'?'0.0.0.0':$('#agentBindAddress').value.trim(),allowed_hosts:addresses.values(),recovery_enabled:$('#agentRecovery').checked,password:$('#agentRecoveryPassword').value});
        dirty=false;if(check())await render(check,target,api);
      } catch(error){if(check())$('#agentAccessError').textContent=error.message;}
      finally{if(button.isConnected)button.disabled=false;}
    };
    if($('#agentRestart'))$('#agentRestart').onclick=async()=>{
      if(!window.confirm('重启目标后台会中断控制台和 Mesh 连接。Windows 终端会话将结束。现在重启？'))return;
      $('#agentRestart').disabled=true;
      try{await api('/agent/settings/restart',{});$('#agentAccessNotice').textContent='后台正在重启，请稍后重新连接。';}
      catch(error){$('#agentAccessError').textContent=error.message;}
    };
  }
  async function canLeave(){if(!dirty)return true;if(!window.confirm('放弃尚未保存的访问设置？'))return false;dirty=false;return true;}
  return {render,canLeave,reset:()=>{dirty=false;}};
})();
