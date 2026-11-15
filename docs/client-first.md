# 客户端优先迁移

本轮依据《OpenRemoteHub 客户端优先架构重构设计 v1.0》实施第一批桌面闭环。附件描述目标能力，现有实现以源码和实际验证为准。

## 文件级方案

| 路径 | 本轮处理 |
| --- | --- |
| `cloud/`、`portal/` | 保留账号、绑定、心跳、设备元数据及 Ticket |
| `mesh/internal/forward/console.go` | 保留身份核验、每设备独立来源、HTTP、WebSocket、流和 DSH 转发 |
| `app/cloud_agent.py` | 目录查询增加可报告错误的调用方式，保留既有调用行为 |
| `app/client.py` | 新增稳定设备目录模型与按设备 ID 建立连接的 API |
| `static/client.*` | 新增设备选择、诊断和账号入口 |
| `static/app.js`、`static/cloud-auth.js` | 复用登录和模块页面，增加客户端返回路径与目标工作区上下文 |
| `scripts/client.py` | 新增 macOS/Linux 原生 WebView 窗口，复用后台启动命令 |
| `windows/orh_launcher.py` | 复用安装、托盘、更新与后台进程，窗口由独立 Client 进程持有 |
| `client/android/` | 保留既有应用内 WebView 与组网，本批不改终端后端 |

## 模型与生命周期

`device_id` 沿用 Cloud 的 `instance_id` 和本机 `.runtime/instance-id`，不根据 IP 生成设备身份。目录同时返回 Cloud 心跳、Mesh 状态和已发布服务。`currentDeviceId` 表示当前工作区目标，由客户端在选择后保存，返回列表清除。

进入远端先按 Cloud 目录解析 Mesh 地址，复用 Mesh 的目标身份验证，再使用目标专用短期 Ticket 登录。工作区成功读取 `/api/me` 后才显示 Agent 已连接。直连、中继与未建立链路分别展示，心跳在线单独标注。

本批采用设计中的过渡期模式。Client 在同一个原生窗口内装载目标 Agent 的完整现有页面，保留返回设备列表入口。HTTP、Cookie、WebSocket、文件和流继续使用目标专用网关。后台由现有 launchd/systemd/独立 Windows 服务进程持有，窗口进程退出不触发后台停止。显式停止命令与 Windows 托盘的“停止后台并退出”仍可停止服务。

后续批次包括可选模块状态与依赖引导、Windows ConPTY、Android 统一工作区，以及各平台真实跨网络验收。源代码测试不能替代 Windows 与 macOS/Linux 双机的 API、终端 WebSocket、关闭窗口后远端访问和 DERP 场景验证。

## 本批验证

- `tests/test_client.py` 与 Cloud、连接、Windows、身份和认证相关测试共 69 项通过。`node tests/client-ui.mjs` 通过设备选择、错误状态、链路显示、原生终端入口及未保存编辑返回保护。
- Go `internal/forward`、`internal/api` 测试通过，覆盖原有目标身份核验、隔离来源、Cookie、HTTP 与 WebSocket 转发。
- macOS 原生窗口完成账号登录、设备目录、Mac 工作区、Docker 列表、返回列表，以及独立 Zellij 测试会话的真实输入输出、关闭子窗口和重新接入。测试会话已退出。
- 关闭全部 Client 窗口后，既有 Agent 和独立测试 Agent 均继续返回 HTTP 200，Mesh 仍为 Running。独立测试服务随后已清理。正式后台需重启加载此次源码更新，Windows 安装包版本已设为 0.6.0，尚待 Windows 构建及实机验收。
- 实际经 Mesh 连接在线 Windows Agent，目标专用 Ticket 兑换及 `/api/me`、`/api/system` 均返回 200，链路曾报告 P2P 直连。该设备仍运行旧版，`/api/capabilities` 返回 404，Docker 返回缺少依赖的 503。新版 Windows 安装包及目标侧工作区导航仍需升级验收。
- `workflow-ui.mjs` 的旧密码表单断言、`workspace-ui.mjs` 缺少 `navigator` 的模拟环境在原始 HEAD 同样失败。新增 Client 交互测试单独通过。

桌面窗口使用 pywebview，共享状态桥接终端子窗口，沿用 Agent 的 CSP。参考 [pywebview 共享状态文档](https://pywebview.flowrl.com/guide/interdomain)。
