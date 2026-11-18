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

新 Agent 在首次登录前建立模块状态，终端、文件和进程与服务默认开启，其他可选功能默认关闭。已有绑定或本机凭据的旧安装保留已有入口。模块依赖状态支持未启用、缺少依赖、可用和不可用。依赖安装由用户在明确选择后完成。已启用模块集中显示在设备工作区，扩展模块收纳在“进阶功能”。停用功能保留外部软件和现有任务。

原生窗口、托盘和 Agent 分进程。macOS 使用用户 LaunchAgent，Linux 优先使用用户 systemd，Windows 使用启动项与独立后台进程。Agent 持有 Mesh 生命周期和 ConPTY 会话。Zellij 的会话进程独立运行。Unix 会话进入与管理操作共用同名锁。结束操作先尝试原生命令，IPC 无响应时按目标 PID 与创建时间结束其进程树。删除前备份目标布局，随后直接清理目标缓存目录。重命名后的目录保存 `orh-process.json`，以 PID 和创建时间关联仍保留原始命令行的进程。

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

## 控制端服务入口

控制台网关 `/__remotehub__/open` 在当前查看设备执行，核验目标 Agent 现有登录会话及设备 ID。远程桌面入口创建控制端到目标 Mesh `21118` 的通用 TCP 转发，与设备列表使用相同路径。

已保存的“当前主机端口”应用通过 Agent `/api/applications/{id}/tunnel` 的二进制 WebSocket 传输 TCP 数据。Agent 核验现有会话、来源与已启用模块，从目标私有应用记录读取端口并连接本机回环地址。控制端以独立 `app-设备ID-应用ID.localhost` 主机名提供应用入口，应用自己的 HTTP Cookie 与 ORH 控制台 Cookie 按主机隔离。HTTP 与应用 WebSocket 复用标准反向代理，将 Host 和同源 Origin 转为目标本机服务地址，并将本机绝对重定向映射回应用入口。HTTPS 保留端到端 TCP 字节转发，由浏览器校验证书。两种方式都通过 Agent 的二进制通道传输，目标服务无需另行发布 Mesh 端口。Cloud 继续仅提供账号及设备元数据。

DSH 状态检测会通过官方 launch token 恢复本机 Cookie。源码版迁移遗漏认证时，可从同用户、通过 PID 和创建时间验证的 ORH DSH supervisor 接续私有认证记录。原进程继续运行，后续 Cookie 刷新由安装版保存。认证失败时提供明确状态及恢复按钮，单独重启仅作用于 ORH 管理的 DSH supervisor。

## 组件化配置与应用壳层（0.6.16）

设备工作区保留顶部返回设备入口，侧栏提供基本工具、连接与网络、功能管理和进阶功能。软件设置与关于页面固定在侧栏底部，通过控制端 Client 访问本机软件 API。桌面和 Android 复用组件化 Web 配置表单，Android 的软件级入口由原生页面承接。

`/api/client/software` 复用 launcher 的发行资产选择与平台安装流程，提供检查、下载进度和安装状态。Cloud 不参与安装包下载和设备业务流量。Windows 使用安装器更新后重启应用，桌面原生菜单仅在 macOS 按系统习惯保留。

DSH 独立桌面窗口与主窗口共用 pywebview 用户配置和 Cookie 存储，Android 共用当前 WebView。设备网关同时转换 DSH 登录错误页面中的目标登录地址。页面操作事件限定在自身组件内，避免匹配到设备工作区根节点。

## Windows 宿主工具发现（0.6.17）

程序发现同时读取当前 PATH、Windows 安装注册信息和 Docker Desktop / RustDesk 的标准用户及系统安装位置。Docker 的模块检测、容器操作与日志使用同一解析结果，安装后重新检测即可识别。程序已安装且 Engine 尚未就绪时，页面显示后台状态并提供打开 Docker Desktop 的入口。

Windows RustDesk 使用官方 CLI 查询设备 ID，通过实际进程与本机 TCP 端口判断运行和直连接入状态。RustDesk 1.5.3 的 Windows 本机管理通道包含进程身份与权限检查，ORH 的安全设置入口转到原生客户端。Unix 平台继续使用现有 IPC 适配。节点小宝在 Windows 复用已验证的本地 HTTP API。其他尚未适配的模块逐项展示实际依赖原因。

## Windows DSH（0.6.18）

Windows 安装检测读取 DeepSeek Harness 的安装注册信息和标准用户、系统安装位置。ORH 使用桌面版官方 `dsh.cmd` 对应的 Electron Node 启动参数，运行 ASAR 中的 CLI 入口，并将 `ELECTRON_RUN_AS_NODE` 仅传给 DSH 子进程。CLI 安装保持原有检测入口。

托管 Supervisor 使用独立 Windows 进程组并隐藏控制台窗口，继续复用官方 launch-token 到 Cookie 的认证交换。Agent 重启后保留 Supervisor，显式重启 DSH 时先结束其所属子进程树，Supervisor 从输出 EOF 退出。HTTP、WebSocket、内嵌工作台和独立入口沿用已有认证网关和共享前端。
