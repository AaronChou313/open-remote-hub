# 架构

ORH 围绕私有组网与远程管理控制台组织四种职责由同一电脑安装包协同运行。Client 选择设备并持有工作区页面，Agent 提供本机能力，Mesh 建立加密设备连接，Cloud 维护账号与设备元数据。

## 连接和身份

`instance_id` 同时作为 Client 的 `device_id`，长期身份保存在 Agent 私有目录。Cloud 设备目录提供当前 Mesh 地址和发布端口。Client 通过 Mesh 校验目标身份后取得目标专用短期 Ticket，目标 Agent 兑换为现有 Cookie 会话。

Go 网关为每台设备分配独立 `.localhost` Origin，保持 Cookie、WebSocket、流式响应、上传下载与 DSH 网关的语义。桌面网关把 `/`、`/auth/cloud` 和 `/static/` 的 GET 请求交给控制端本机的前端服务，其余请求经 Mesh 到目标 Agent。Android WebView 从 APK assets 提供同一套前端文件，API 保持目标来源。

Cloud API 承载账号、目录、授权与协调。终端和文件等管理流量走 Mesh。采用 DERP 时，中继承担对应流量。Cloud 心跳与 Agent API 可达性分别呈现。

## 主要模块

| 路径 | 职责 |
| --- | --- |
| `app/launcher.py`、`desktop/` | 安装后运行目录、后台服务、托盘、窗口和更新 |
| `app/desktop_client.py` | 原生 WebView 主窗口、受控终端子窗口 |
| `app/client.py`、`static/client.*` | 设备目录、按设备连接、诊断与账号 |
| `static/client-workspace.js` | 目标工作区上下文、身份验证、链路状态和返回保护 |
| `app/modules.py`、`static/modules.js` | 可选模块状态、平台与依赖检测、启停引导 |
| `app/main.py`、`app/platforms.py` | 系统状态、鉴权、Docker、进程与平台服务 |
| `app/cloud_agent.py`、`app/discovery.py` | 长期身份、绑定、心跳和 Ticket 兑换 |
| `app/mesh_runtime.py` | 内置 Mesh 子进程、配置和生命周期 |
| `app/terminal_entry.py`、`app/native_terminal.py` | Unix Zellij 会话和认证网关 |
| `app/conpty.py`、`static/conpty.*` | Windows Agent 持有的 PowerShell/cmd 会话和 WebSocket |
| `app/files.py`、`app/windows_files.py`、`app/file_access.py` | 授权目录与平台原生文件操作 |
| `app/remote_connect/` | Mesh LocalAPI 与 RustDesk 平台适配 |
| `app/ssh/`、`app/projects.py`、`app/environments.py` | SSH、项目、开发环境 |
| `app/dsh.py`、`app/dsh_gateway.py`、`scripts/dsh_host.py` | DSH 原生工作台及同源网关 |
| `app/proxy*.py`、`scripts/proxy*.py` | 可选 Mihomo broker 与配置 |
| `mesh/internal/forward/` | 设备网关、HTTP/WebSocket 转发及隔离来源 |
| `mesh/internal/api/`、`mesh/mobile/` | 本机组网 API、Cloud 同步、Android 核心 |
| `mesh/web/` | 只读组网诊断页面 |
| `client/android/` | Android 设备目录、后台 Mesh、内嵌共享工作区和 RustDesk 调用 |
| `cloud/`、`portal/` | 账号、设备元数据、Headscale 协调和管理后台 |

## 模块与生命周期

新 Agent 在首次登录前建立模块状态，终端、文件和进程与服务默认开启，其他可选功能默认关闭。已有绑定或本机凭据的旧安装保留已有入口。模块依赖状态支持未启用、缺少依赖、可用和不可用。依赖安装由用户在明确选择后完成。已启用模块集中显示在设备工作区，扩展模块收纳在“更多功能”。停用功能保留外部软件和现有任务。

原生窗口、托盘和 Agent 分进程。macOS 使用用户 LaunchAgent，Linux 优先使用用户 systemd，Windows 使用启动项与独立后台进程。Agent 持有 Mesh 生命周期和 ConPTY 会话。Zellij 的会话进程独立运行。

macOS 上 RustDesk 的启动与连接通过 `/usr/bin/open -n -a RustDesk.app --args ...` 交给 LaunchServices，屏幕采集的 TCC 归属 RustDesk。系统授权仍由用户授予 RustDesk。

## 数据与构建

用户文件、Docker、终端、项目与密钥位于目标电脑。Cloud 保存账号与设备元数据。手动地址和备注独立于 Agent 上报地址保存。Cloud 解绑撤销设备凭据和入网授权，离线 Agent 在恢复联系后同步撤销。

桌面包使用 PyInstaller，包含 Python、WebView 适配、Agent 与 Go Mesh。Linux 包包含 Qt WebEngine。Android 通过 gomobile 引入同一 Go 核心并打包共享静态页面。`VERSION` 为版本号来源，CI 产出 Windows EXE、两种 Mac 架构的 DMG、Linux DEB 和 Android 签名 APK。

## 共享入口与组网管理

桌面入口由 `static/client.*` 提供“我的设备 / 组网状态 / 设置”。目标 `/` 保留完整 Web 控制台，继续与 Client 网关、Android assets 复用 `static/index.html`、模块组件和同一 Agent API。

`static/mesh.js` 在 Client 与 Web 中复用。`/api/client/mesh*` 使用现有 ORH Mesh LocalAPI 提供状态、P2P / DERP 诊断、TCP 转发与关闭。发布服务继续由 `mesh_runtime.save_config` 管理。备用 Tailscale、节点小宝由外部软件持有生命周期。

Android 使用相同的一级导航，设备卡片以“打开控制台”为主操作。点击后立即打开控制台加载页，由该页面异步建立目标通道和交换账号 Ticket。加载失败保留错误与重试入口。Android 的账号登录与 Ticket 请求统一复用 Go Cloud 传输，账号 Token 仅在本次请求内使用。目标工作区仍使用打包的共享 Web 页面。

## 备用监听与恢复认证

`app/agent_settings.py` 在目标私有目录保存 `agent-settings.json`，覆盖监听地址与允许的目标 Host，并保存本地恢复开关。地址校验复用 `app/network.py`。允许地址即时更新，监听变更通过安装版后台重启生效。指定备用 IP 时保留 IPv4 回环入口。备用网卡尚未就绪时继续启动本机 API，并在设置页报告备用监听错误，避免备用网络的启动顺序影响本机恢复。Agent API 的启动与认证均独立于 Mesh 可达性。

恢复密码复用现有 PBKDF2 密码存储，以独立会话凭据指纹识别。Cloud 绑定后默认沿用账号登录，用户主动开启恢复后，可在 Cloud 离线时使用本地密码。密码轮换和关闭恢复使对应恢复会话失效，现有 Cloud 会话继续按账号指纹验证。本机交互式 `password.py --recovery` 用于故障恢复。

Client 以账号指纹绑定私有设备目录缓存。Cloud 返回连接失败时可展示缓存目录，通过 Mesh 网关核验目标长期 ID 后，允许目标现有会话或本地恢复登录。Cloud 明确拒绝账号授权时继续返回账号错误。恢复密码仅在目标 Agent 校验。

## Android 与系统 VPN 并行

`mesh/mobile` 使用应用内 tsnet。Android Manifest 仅声明 `connectedDevice` 前台 Mesh 服务，保持系统 VPN 槽位可用。`MeshService` 与 Activity 独立，使用既有网络重绑定、前台通知及活动转发保活。通用本地 TCP 转发为外部 App 提供接入。Activity 切换与销毁仅关闭界面资源。
