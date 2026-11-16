# 架构

ORH 的四种职责由同一电脑安装包协同运行。Client 选择设备并持有工作区页面，Agent 提供本机能力，Mesh 建立加密设备连接，Cloud 维护账号与设备元数据。

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

新 Agent 在首次登录前建立模块状态，全部可选功能默认关闭。已有绑定或本机凭据的旧安装保留已有入口。模块依赖状态支持未启用、缺少依赖、可用和不可用。依赖安装由用户在明确选择后完成。停用功能保留外部软件和现有任务。

原生窗口、托盘和 Agent 分进程。macOS 使用用户 LaunchAgent，Linux 优先使用用户 systemd，Windows 使用启动项与独立后台进程。Agent 持有 Mesh 生命周期和 ConPTY 会话。Zellij 的会话进程独立运行。

macOS 上 RustDesk 的启动与连接通过 `/usr/bin/open -n -a RustDesk.app --args ...` 交给 LaunchServices，屏幕采集的 TCC 归属 RustDesk。系统授权仍由用户授予 RustDesk。

## 数据与构建

用户文件、Docker、终端、项目与密钥位于目标电脑。Cloud 保存账号与设备元数据。手动地址和备注独立于 Agent 上报地址保存。Cloud 解绑撤销设备凭据和入网授权，离线 Agent 在恢复联系后同步撤销。

桌面包使用 PyInstaller，包含 Python、WebView 适配、Agent 与 Go Mesh。Linux 包包含 Qt WebEngine。Android 通过 gomobile 引入同一 Go 核心并打包共享静态页面。`VERSION` 为版本号来源，CI 产出 Windows EXE、两种 Mac 架构的 DMG、Linux DEB 和 Android 签名 APK。
