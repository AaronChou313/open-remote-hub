import assert from "node:assert/strict";
import fs from "node:fs";
import vm from "node:vm";
const nodes = new Map(),
  calls = [];
let closeButtons = [];
function element() {
  let html = "";
  return {
    value: "",
    textContent: "",
    checked: false,
    hidden: false,
    disabled: false,
    isConnected: true,
    dataset: {},
    get innerHTML() {
      return html;
    },
    set innerHTML(value) {
      html = value;
      for (const match of value.matchAll(/\bid="([^"]+)"/g))
        nodes.set("#" + match[1], element());
      closeButtons = Array.from(
        value.matchAll(/data-mesh-close="([^"]+)"/g),
        (match) => ({ ...element(), dataset: { meshClose: match[1] } }),
      );
    },
  };
}
nodes.set("#content", element());
const state = {
  bind: "127.0.0.1",
  allowed_hosts: ["10.77.1.2"],
  recovery_enabled: false,
  restart_required: false,
  urls: [],
};
const mesh = {
  status: {
    state: "Running",
    device: { hostname: "Mac", addresses: ["100.64.0.17"] },
    peers: [
      {
        hostname: "Linux",
        addresses: ["100.64.0.9"],
        route: "direct",
        online: true,
      },
    ],
  },
  forwards: [
    {
      id: "a".repeat(24),
      peer_ip: "100.64.0.9",
      remote_port: 22,
      local_port: 10022,
      connections: 1,
    },
  ],
};
const api = async (path, body) => {
  calls.push({ path, body });
  if (path === "/client/mesh") return mesh;
  if (path === "/agent/settings") return state;
  return { ok: true };
};
const ctx = vm.createContext({
  window: { confirm: () => true },
  RemoteHubFormControls:{escape:value=>String(value ?? ''),list:(selector,values)=>{nodes.get(selector).value=values.join('\n');return {values:()=>nodes.get(selector).value.split(/\s+/).filter(Boolean)}},facts:value=>String(value)},
  document: {
    querySelector: (s) => nodes.get(s) || null,
    querySelectorAll: (s) => (s === "[data-mesh-close]" ? closeButtons : []),
  },
});
for (const file of ["mesh", "agent-settings"])
  vm.runInContext(fs.readFileSync("static/" + file + ".js", "utf8"), ctx);
const $ = (s) => nodes.get(s);
await ctx.window.RemoteHubMesh.render(() => true, "#content", api);
assert.match($("#content").innerHTML, /P2P 直连/);
$("#meshPeer").value = "100.64.0.9";
$("#meshRemotePort").value = "22";
$("#meshLocalPort").value = "10022";
$("#meshForwardForm").oninput();
const before = calls.length;
await ctx.window.RemoteHubMesh.render(() => true, "#content", api);
assert.equal(calls.length, before, "Polling keeps a TCP mapping draft");
$("#meshForwardForm").onsubmit({ preventDefault() {} });
await new Promise((resolve) => setImmediate(resolve));
assert.deepEqual(
  JSON.parse(
    JSON.stringify(calls.find((c) => c.path === "/client/mesh/forward").body),
  ),
  { peer_ip: "100.64.0.9", remote_port: 22, local_port: 10022 },
);
await closeButtons[0].onclick();
assert.equal(calls.at(-2).path, "/client/mesh/close");
await ctx.window.RemoteHubAgentSettings.render(() => true, "#content", api);
$("#agentAccessMode").value = "network";
$("#agentAllowedHosts").value = "10.77.1.2\n100.100.1.2";
$("#agentRecovery").checked = true;
$("#agentRecoveryPassword").value = "fixture-recovery-password";
await $("#agentAccessForm").onsubmit({ preventDefault() {} });
const saved = calls.find(
  (call) => call.path === "/agent/settings" && call.body,
);
assert.equal(saved.body.bind, "0.0.0.0");
assert.equal(saved.body.recovery_enabled, true);
assert.equal(saved.body.allowed_hosts.join(","), "10.77.1.2,100.100.1.2");
assert.equal(
  $("#agentRecoveryPassword").value,
  "",
  "Saved recovery secret is cleared",
);
console.log(
  "Shared Mesh and Agent settings support generic TCP mappings, draft preservation and local recovery settings.",
);
