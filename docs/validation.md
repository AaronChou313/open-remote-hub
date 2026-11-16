# 验证记录

## 0.6.10 增量

Python 全量检查通过 296 项，另有 12 项真实服务检查按现有设置排除。共享前端交互脚本覆盖设备主入口、模块导航、Mesh TCP 转发、草稿保护和备用访问设置。Go 内部模块通过 race 测试，新增 Ticket 检查确认使用已绑定 Cloud、保持账号错误状态并排除无效设备路径。

macOS 打包 Agent 在独立运行目录执行核心、文件与任务检查。通过安装版交互式恢复命令设置测试密码后，配置备用监听并重新启动，经真实局域网地址访问 Web API 成功，测试过程中该 Agent 的 Mesh 保持关闭。缺失备用接口与 IPv6 配置的回归检查确认本机 IPv4 回环入口继续保留。绑定模式下的本地恢复、密码轮换、Cloud 会话保持和不同账号目录缓存隔离由 API 回归覆盖。

共享页面实际点击验证“我的设备 → 打开控制台”、模块导航、文件页、Mesh 诊断和访问设置。真实 Mesh 到 Windows 的连通性检查返回 P2P 直连。

Android 35 ARM64 模拟器复现了 Java 获取 Cloud Ticket 时的 `SSLHandshakeException connection closed`。Ticket 改为复用现有 Go Cloud 传输后，模拟器通过真实 Mesh、目标 Ticket 和 Cookie 登录，成功打开安装版 Mac Agent 的共享控制台。点击入口改为立即创建控制台页面，在页面内异步准备连接，失败保留错误与重试。Android 发布构建与 lint 通过，Manifest 回归检查保留应用内组网和独立 connectedDevice 前台服务。

网络页同时修复 RustDesk、节点小宝及局域网子页对旧摘要元素的引用。现有 macOS Mihomo 后台与两份机场配置已恢复识别，代理进程与流量保持连续运行。Mihomo 新装流程在隔离 Linux 环境启动实际 broker 与内核，使用临时服务管理适配器。x64 下载使用官方 v1 CPU 基线构建。macOS 菜单栏进程 activation policy 为 accessory，原生窗口为 regular，只有一个进程显示 Dock 图标。

## 0.6.8 历史验证

### 自动检查

Python 全量测试通过 282 项。前端交互脚本覆盖设备选择、账号错误、链路状态、模块路由、终端、上传、编辑保护及原有模块。Go 测试覆盖目标身份、隔离 Origin、Cookie、HTTP/WebSocket 和本机前端与目标 API 的分流。

Windows 安装包构建后执行实际 Agent，检查新安装默认关闭模块、文件上传和 Range 下载、回收恢复、后台任务启停、ConPTY 命令执行、尺寸调整与重连。Linux 与两种 Mac 架构执行打包 Agent 的核心、模块、文件和任务检查。Android 正式签名包构建与 lint 通过。干净 Ubuntu 容器实际安装 DEB 后验证原生 Qt 窗口启动，补齐 XCB、GLib 和 Fontconfig 依赖，并在 Linux 构建流程加入原生窗口启动检查。

### 真实设备通道

本机已安装 macOS 应用并使用用户 LaunchAgent，沿用原有设备身份与账号绑定。原生窗口显示同账号 Mac 和 Windows，读取本机系统指标和模块状态。早期原生窗口已验证 Zellij 输入、子窗口关闭和重新接入，关闭全部界面后 Agent 与 Mesh 仍继续运行。

最终 0.6.8 在 Windows 实机完成安装升级。实际打包进程创建原生 WebView，使用保存的账号进入设备目录，随后关闭测试窗口。通过 Mesh 验证 ConPTY 命令、尺寸变化、会话重连、文件上传、Range 下载和回收恢复，显式停止后台后确认打包 Mesh 退出并重新启动。反向由 Windows 的打包运行时连接 Mac，读取系统信息并启动、停止、重启专门创建的 Docker 测试容器。测试容器、辅助脚本、临时安装文件及测试任务已清理。

Linux 最终 DEB 在干净 Ubuntu 22.04 中通过 apt 安装，自动补齐 CA 证书及系统库。Cloud 登录、默认关闭可选模块、快速命令、文件上传、Range 下载和回收恢复均通过。Mac 还通过真实 Mesh 与目标 Ticket 访问该 Linux Agent，核验目标身份并读取系统及文件 API。旧版 OpenSSL 的 Cloud 握手问题已通过更新打包运行时解决。

macOS ARM 发行包使用已通过完整矩阵检查的构建，源码树与发布标签一致，并已在本机验证原生窗口、账号恢复及 Windows 工作区。该产物来自 [CI 构建记录](https://github.com/AaronChou313/open-remote-hub/actions/runs/43845587907)。

Android 35 ARM64 模拟器使用正式签名 APK，实际接入同一账号 Mesh，连接安装版 Mac Agent。通过目标 Ticket、系统 API、终端真实输入输出、关闭 WebSocket 后重新接入、文件上传、Range 下载和回收恢复。正常网络记录为 P2P 直连。临时关闭目标直连传输后，同一组终端与文件测试在 DERP 中继路径重复通过，随后恢复正常组网配置。测试会话和测试文件已清理。

Cloud 元数据更新已部署，HTTPS 健康接口成功，Headscale 正常运行。设备备注、手动地址及 `controller-only` 由对应 API 测试覆盖。

### RustDesk

macOS 的自启、桌面连接、文件传输全部使用 LaunchServices。回归测试检查 `/usr/bin/open -n -a RustDesk.app --args ...`，避免 Python 成为屏幕采集 responsible process，并让已有 RustDesk 实例能接收新的连接参数。用户已恢复的运行实例在 replayd 日志出现 `TCC Allow`。

### 平台范围

CI 验证对应操作系统上的实际程序执行。macOS 包要求 macOS 15 及以上，Linux DEB 面向 Ubuntu 22.04 / Debian 12 及以上。Android 真实手机/平板的厂商后台策略、不同运营商网络的稳定性、屏幕录制和辅助功能权限、登录前桌面访问依赖具体设备与系统设置。macOS 包尚未获得 Apple 开发者公证，Windows 包尚无 Authenticode 证书。
