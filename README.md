# OpenRemoteHub

私有组网与远程设备管理控制台。在“我的设备”选择电脑，打开系统概览、终端、文件与服务管理。内置 Mesh 提供 P2P / DERP 连接、诊断和通用 TCP 转发。桌面安装包包含 Client、Agent 和 Mesh，Android 提供应用内组网与控制端。
## 安装与使用

从 [Releases](https://github.com/AaronChou313/open-remote-hub/releases/latest) 下载对应安装包。

| 平台 | 安装包 | 安装方式 |
| --- | --- | --- |
| Windows 10/11 x64 | `ORH-Setup-0.6.16.exe` | 运行安装向导，从开始菜单打开 |
| macOS 15+ Apple Silicon | `OpenRemoteHub-0.6.16-macos-arm64.dmg` | 把应用拖入 Applications |
| macOS 15+ Intel | `OpenRemoteHub-0.6.16-macos-amd64.dmg` | 把应用拖入 Applications |
| Ubuntu 22.04+ / Debian 12+ x64 | `OpenRemoteHub-0.6.16-linux-amd64.deb` | 软件安装器打开，或 `sudo apt install ./OpenRemoteHub-0.6.16-linux-amd64.deb` |
| Android 8+ ARM64 | `OpenRemoteHub-0.6.16-android-arm64.apk` | 下载 APK 后安装 |

桌面包自带 Python 运行时和 Mesh，使用时无需安装开发工具。Linux 包自带 Qt WebEngine，其系统库依赖由包管理器安装。macOS 包采用本地签名，目前没有 Apple 开发者公证。Windows 包目前没有 Authenticode 证书。Android 正式包使用固定发布密钥，旧调试版需要先卸载一次，再安装正式版。

1. 打开 ORH，已有账号可直接登录，新用户点击“没有账号？注册账号”，注册后返回客户端登录。默认 Cloud 已开放注册，自建服务可通过 `ORH_CLOUD_INVITE_REQUIRED` 选择邀请码模式。默认服务为 `https://cloud.openremotehub.top`。
2. 在“我的设备”选择电脑，点击“打开控制台”。终端、文件、进程与服务和本地局域网默认启用，可在目标设备的“功能管理”启用其他模块。
3. 关闭窗口后，后台 Agent、Mesh 和会话继续运行。通过托盘或 macOS 菜单栏重新打开窗口，可显式停止后台。软件更新在“关于 ORH”页查看、下载和安装。

macOS 使用用户 LaunchAgent，Linux 使用用户 systemd 服务，Windows 使用用户启动项。这些机制随用户登录启动。无头 Linux 可运行 `openremotehub --headless`。需要用户服务在退出登录后持续运行时，可由管理员为对应用户启用 systemd lingering。

Android 需要按应用内提示允许通知和后台运行。第一阶段只控制电脑，设备目录标记为 `controller-only`。远程桌面会调用已安装的 RustDesk。使用 ORH 私有组网访问 Agent，无需手填 IP 或路由器端口映射。

## 可选功能

新安装默认启用终端、文件、进程与服务和本地局域网。其他可选模块按需启用。功能管理固定在基本导航，区分基本功能与进阶功能，并显示未启用、缺少依赖、可用和不可用四种状态及安装说明。

| 功能 | 支持与依赖 |
| --- | --- |
| 系统概览、账号、设备选择、Mesh、诊断 | 核心自带 |
| 终端 | macOS/Linux 使用 Zellij，Windows 自带 ConPTY 后端和 PowerShell/cmd 接入 |
| 文件 | 三个桌面平台原生支持，包含授权目录、上传下载、编辑、复制移动和回收恢复 |
| Docker | 三个桌面平台，需要 Docker CLI 和可访问的 Engine |
| 远程桌面 | 三个桌面平台及 Android 控制端，需要 RustDesk 和对应系统权限 |
| 进程与服务 | macOS launchd、Linux systemd、Windows Services |
| SSH、项目、开发环境、知识库、DSH、网络代理 | macOS/Linux。按功能检测宿主机依赖，Windows 界面明确显示支持状态 |

macOS / Linux 可在“功能管理”启用网络代理，然后点击“前往安装 → 安装 Mihomo”，在目标主机完成系统管理员授权。已有 ORH Mihomo 后台自动识别，机场配置保存在目标主机。

Windows ConPTY 由 Agent 持有进程，关闭终端窗口后可重新接入。macOS/Linux 复用 Zellij 会话与原生 Web Client。停用模块保留用户已安装的第三方软件和已有任务。macOS 的 RustDesk 启动、连接和文件传输统一经过 LaunchServices，屏幕录制权限归属 RustDesk 应用。

## 连接方式

Client 按长期 `device_id` 选择设备，经 Mesh 校验目标身份，再兑换目标专用短期 Ticket。工作区读取目标 `/api/me` 成功后才显示 Agent 已连接。Cloud 心跳、Agent 可达性、P2P 直连和 DERP 中继各自展示。

桌面共享导航和页面资源由本机 Client 提供，Android 使用 APK 内的共享页面资源。HTTP API、WebSocket、文件和终端流量通过目标设备独立的 `.localhost` 网关传输。优先 P2P，底层使用 DERP 时，中继会承载相应流量。

[Cloud 后台](https://cloud.openremotehub.top/) 管理账号、设备名称、备注、手动访问地址和解绑。组网 IP 由组网控制平面分配。手动地址与设备自动上报地址独立保存。

## 独立 Web 应用

在目标设备的“进程与服务”找到 HTTP / HTTPS 端口，点击加号添加到“我的应用”。也可手动填写“当前主机端口”。在 Client 的远端工作区点击“打开应用”后，ORH 在控制端建立独立的本地访问地址，经目标 Agent 的认证连接转发到服务端口。已有应用入口可以直接使用更新后的连接方式。

- 目标服务需要正在运行，并监听 `127.0.0.1` 或全部网卡。此方式支持仅本机监听的 Web 服务。
- HTTP 通道会转换本机 Host 与同源 Origin，并处理本机绝对重定向，服务可保留 localhost 访问检查。服务可以使用相对路径、WebSocket 和自己的登录认证。若应用配置了固定公网域名、绝对回调地址或 Host 白名单，需要按该应用的配置方式允许当前访问地址。
- HTTPS 服务仍由浏览器验证其证书。绑定固定域名和证书的服务可使用“自定义网址”。
- 从普通浏览器直接访问备用网络的 Agent Web 页面时，“当前主机端口”使用目标主机地址，服务需要允许该网络访问，目标防火墙需放行服务端口。

本地局域网、节点小宝、网络代理、远程桌面是独立模块。节点小宝继续由其客户端管理。远程桌面页的连接按钮复用 ORH 控制端通道，目标设备需启用 RustDesk IP 直连。

DSH 在目标电脑安装 DeepSeek Harness 后，可从“功能管理”启用。ORH 自动检测桌面版或命令行安装，首次进入使用原生工作台配置模型账号。认证异常可在模块内恢复，单独重启 DSH 会提示正在运行的模型任务受到影响。

## Web 控制台、备用网络与离线恢复

目标 Agent 保留完整 Web 控制台。桌面 Client 与 Web 复用同一套系统、终端、文件、Docker 和其他模块页面。可通过 `http://设备IP:8765` 访问已配置的目标地址。

1. 在目标设备的“设备访问设置”选择“允许局域网和备用网络”，或选择“指定本机网络地址”填写监听 IP。
2. 将局域网、官方 Tailscale、节点小宝等备用网络的本机 IP 加入允许地址列表。地址变化后同步更新列表。指定备用监听 IP 时，本机回环入口会继续保留。
3. 按需启用独立本地恢复密码，保存设置并重启后台。Cloud 不可用时，在目标 Web 登录页展开“本地恢复登录”。正常访问继续使用 ORH 账号。

备用组网由对应软件独立运行。Agent 的本机管理 API 独立于 Mesh。Cloud 暂时不可用时，Client 保留该账号已缓存的设备目录，已可达的 Mesh 网关可打开目标恢复登录页。

忘记恢复密码时，可在目标电脑的本机终端运行交互式恢复命令，密码通过交互输入。

```sh
# macOS 安装版
/Applications/OpenRemoteHub.app/Contents/MacOS/OpenRemoteHub --run-script password.py --recovery
# Linux 安装版
openremotehub --run-script password.py --recovery
# Windows 安装版，在 PowerShell 中运行
Start-Process -FilePath "$env:LOCALAPPDATA\Programs\OpenRemoteHub\OpenRemoteHub.exe" -ArgumentList @("--run-script", "password.py", "--recovery") -NoNewWindow -Wait
# 源码运行
.venv/bin/python scripts/password.py --recovery
```

在“组网状态”选择目标设备与 TCP 端口，可创建 `127.0.0.1:本地端口` 转发。目标服务需在目标设备的“本机组网与发布端口”中发布，例如 `22=127.0.0.1:22` 或 `80=127.0.0.1:8080`。此通道可用于 SSH、HTTP 与 RustDesk 等 TCP 服务。

Android 使用应用内 tsnet，保持与系统 VPN 并行运行。外部 App 通过本地映射端口使用 ORH 网络，Mesh 前台服务在切换应用后继续运行。Android 厂商的电池与后台设置仍需在对应设备上放行。

## 配置与数据

| 平台 | Agent 数据目录 | Mesh 身份目录 |
| --- | --- | --- |
| macOS | `~/Library/Application Support/OpenRemoteHub` | `~/Library/Application Support/orh-mesh` |
| Windows | `%LOCALAPPDATA%\OpenRemoteHub` | `%APPDATA%\orh-mesh` |
| Linux | `~/.local/share/openremotehub` | `~/.config/orh-mesh` |

Agent 的 `.env` 保存本机监听与文件目录配置，`.runtime` 保存绑定、模块状态、会话认证和业务元数据。默认监听回环地址，由 Mesh 发布访问。可在“设置 → Web 控制台与本地恢复”配置其他监听地址与允许访问的本机 IP，保存后使用“重启后台并应用”生效。文件授权目录通过 `ORH_FILE_ROOTS` 的 JSON 数组配置。已有 macOS 源码 LaunchAgent 会迁移设备身份与账号绑定，并由安装版接管后台。

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

## 设置与软件信息

桌面与 Android 提供“设置”和“关于 ORH”入口。关于页展示版本、检查结果和更新说明，并提供安装包下载。Windows 可在页内安装更新并重启，macOS / Linux 打开系统安装包完成安装。

设备访问地址、组网发布端口、代理 DNS 和 SSH 配置均使用表单组件。地址通过添加、移除管理，端口映射提供 SSH、HTTP、HTTPS 和 RustDesk 模板。代理配置可通过订阅链接或文件导入，表单修改保留已有节点、规则和自定义配置。

DSH 页面填充设备工作区剩余高度。桌面的“独立窗口”在 ORH 内打开并共享登录会话，Android 在应用内打开，工具栏可返回控制台。
