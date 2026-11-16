# OpenRemoteHub

在同一个客户端中选择自己的电脑，使用系统概览、终端、文件、Docker 和远程桌面。电脑安装包包含 Client、后台 Agent 和 Mesh。Android 提供控制端。

## 安装与使用

从 [Releases](https://github.com/AaronChou313/open-remote-hub/releases/latest) 下载对应安装包。

| 平台 | 安装包 | 安装方式 |
| --- | --- | --- |
| Windows 10/11 x64 | `ORH-Setup-0.6.9.exe` | 运行安装向导，从开始菜单打开 |
| macOS 15+ Apple Silicon | `OpenRemoteHub-0.6.9-macos-arm64.dmg` | 把应用拖入 Applications |
| macOS 15+ Intel | `OpenRemoteHub-0.6.9-macos-amd64.dmg` | 把应用拖入 Applications |
| Ubuntu 22.04+ / Debian 12+ x64 | `OpenRemoteHub-0.6.9-linux-amd64.deb` | 软件安装器打开，或 `sudo apt install ./OpenRemoteHub-0.6.9-linux-amd64.deb` |
| Android 8+ ARM64 | `OpenRemoteHub-0.6.9-android-arm64.apk` | 下载 APK 后安装 |

桌面包自带 Python 运行时和 Mesh，使用时无需安装开发工具。Linux 包自带 Qt WebEngine，其系统库依赖由包管理器安装。macOS 包采用本地签名，目前没有 Apple 开发者公证。Windows 包目前没有 Authenticode 证书。Android 正式包使用固定发布密钥，旧调试版需要先卸载一次，再安装正式版。

1. 打开 ORH，登录同一个 ORH Cloud 账号。默认服务为 `https://cloud.openremotehub.top`。
2. 在“我的设备”选择电脑，进入应用内工作区。首次使用到目标电脑的“功能管理”启用需要的模块。
3. 关闭窗口后，后台 Agent、Mesh 和会话继续运行。通过托盘或 macOS 菜单栏重新打开窗口，也可检查更新、显式停止后台。

macOS 使用用户 LaunchAgent，Linux 使用用户 systemd 服务，Windows 使用用户启动项。这些机制随用户登录启动。无头 Linux 可运行 `openremotehub --headless`。需要用户服务在退出登录后持续运行时，可由管理员为对应用户启用 systemd lingering。

Android 需要按应用内提示允许通知和后台运行。第一阶段只控制电脑，设备目录标记为 `controller-only`。远程桌面会调用已安装的 RustDesk。使用 ORH 私有组网访问 Agent，无需手填 IP 或路由器端口映射。

## 可选功能

新安装默认关闭全部可选模块。功能管理显示未启用、缺少依赖、可用和不可用四种状态，并提供检测和安装说明。

| 功能 | 支持与依赖 |
| --- | --- |
| 系统概览、账号、设备选择、Mesh、诊断 | 核心自带 |
| 终端 | macOS/Linux 使用 Zellij，Windows 自带 ConPTY 后端和 PowerShell/cmd 接入 |
| 文件 | 三个桌面平台原生支持，包含授权目录、上传下载、编辑、复制移动和回收恢复 |
| Docker | 三个桌面平台，需要 Docker CLI 和可访问的 Engine |
| 远程桌面 | 三个桌面平台及 Android 控制端，需要 RustDesk 和对应系统权限 |
| 进程与服务 | macOS launchd、Linux systemd、Windows Services |
| SSH、项目、开发环境、知识库、DSH、网络代理 | macOS/Linux。按功能检测宿主机依赖，Windows 界面明确显示支持状态 |

Windows ConPTY 由 Agent 持有进程，关闭终端窗口后可重新接入。macOS/Linux 复用 Zellij 会话与原生 Web Client。停用模块保留用户已安装的第三方软件和已有任务。macOS 的 RustDesk 启动、连接和文件传输统一经过 LaunchServices，屏幕录制权限归属 RustDesk 应用。

## 连接方式

Client 按长期 `device_id` 选择设备，经 Mesh 校验目标身份，再兑换目标专用短期 Ticket。工作区读取目标 `/api/me` 成功后才显示 Agent 已连接。Cloud 心跳、Agent 可达性、P2P 直连和 DERP 中继各自展示。

桌面共享导航和页面资源由本机 Client 提供，Android 使用 APK 内的共享页面资源。HTTP API、WebSocket、文件和终端流量通过目标设备独立的 `.localhost` 网关传输。优先 P2P，底层使用 DERP 时，中继会承载相应流量。

[Cloud 后台](https://cloud.openremotehub.top/) 管理账号、设备名称、备注、手动访问地址和解绑。组网 IP 由组网控制平面分配。手动地址与设备自动上报地址独立保存。

## 配置与数据

| 平台 | Agent 数据目录 | Mesh 身份目录 |
| --- | --- | --- |
| macOS | `~/Library/Application Support/OpenRemoteHub` | `~/Library/Application Support/orh-mesh` |
| Windows | `%LOCALAPPDATA%\OpenRemoteHub` | `%APPDATA%\orh-mesh` |
| Linux | `~/.local/share/openremotehub` | `~/.config/orh-mesh` |

Agent 的 `.env` 保存本机监听与文件目录配置，`.runtime` 保存绑定、模块状态、会话认证和业务元数据。默认仅监听回环地址，由 Mesh 发布访问。文件授权目录通过 `ORH_FILE_ROOTS` 的 JSON 数组配置。已有 macOS 源码 LaunchAgent 会迁移设备身份与账号绑定，并由安装版接管后台。

## 开发与构建

源码开发需要 Python 3.11+。Mesh 使用 Go，Android 使用 JDK 21、Android SDK 35 和 NDK 28.2.13676358。

```sh
python3 -m venv .venv
.venv/bin/pip install -r requirements-dev.txt -r client/requirements.txt
.venv/bin/python scripts/client.py
```

```sh
# macOS/Linux 安装包
.venv/bin/pip install -r desktop/requirements.txt
.venv/bin/python scripts/build_desktop.py

# Windows 安装包，在 PowerShell 中运行
# windows/build.ps1

# Android 正式包，先配置 Android SDK/NDK
.venv/bin/python scripts/build_android.py
```

`VERSION` 是版本号来源。Android 首次本地构建生成私有发布密钥，保存在 `.runtime`，后续发布应保留该密钥。CI 通过仓库 Secrets 使用同一发布密钥。生成的安装包在 `dist/`，构建目录及二进制产物由 Git 忽略。

```sh
.venv/bin/pytest -q
node tests/client-ui.mjs
cd mesh && go test ./internal/...
```

Cloud 部署沿用 `cloud/compose.yml` 和 `cloud/compose.orn.yml`。架构与模块位置见 [架构说明](docs/architecture.md)，本次改造与验证见 [客户端版本说明](docs/client-first.md)。
