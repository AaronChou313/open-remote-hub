# 0.6.2 验证

## 自动检查

Python 全量测试通过 278 项。前端交互脚本覆盖设备选择、账号错误、链路状态、模块路由、终端、上传、编辑保护及原有模块。Go 测试覆盖目标身份、隔离 Origin、Cookie、HTTP/WebSocket 和本机前端与目标 API 的分流。

Windows 安装包构建后执行实际 Agent，检查新安装默认关闭模块、文件上传和 Range 下载、回收恢复、后台任务启停、ConPTY 命令执行、尺寸调整与重连。Linux 与两种 Mac 架构执行打包 Agent 的核心、模块、文件和任务检查。Android 正式签名包构建与 lint 通过。干净 Ubuntu 容器实际安装 DEB 后验证原生 Qt 窗口启动，补齐 XCB、GLib 和 Fontconfig 依赖，并在 Linux 构建流程加入原生窗口启动检查。

## 真实设备通道

本机已安装 macOS 应用并使用用户 LaunchAgent，沿用原有设备身份与账号绑定。原生窗口显示同账号 Mac 和 Windows，读取本机系统指标和模块状态。早期原生窗口已验证 Zellij 输入、子窗口关闭和重新接入，关闭全部界面后 Agent 与 Mesh 仍继续运行。

Android 35 ARM64 模拟器使用正式签名 APK，实际接入同一账号 Mesh，连接安装版 Mac Agent。通过目标 Ticket、系统 API、终端真实输入输出、关闭 WebSocket 后重新接入、文件上传、Range 下载和回收恢复。正常网络记录为 P2P 直连。临时关闭目标直连传输后，同一组终端与文件测试在 DERP 中继路径重复通过，随后恢复正常组网配置。测试会话和测试文件已清理。

Cloud 元数据更新已部署，HTTPS 健康接口成功，Headscale 正常运行。设备备注、手动地址及 `controller-only` 由对应 API 测试覆盖。

## RustDesk

macOS 的自启、桌面连接、文件传输全部使用 LaunchServices。回归测试检查 `/usr/bin/open -n -a RustDesk.app --args ...`，避免 Python 成为屏幕采集 responsible process，并让已有 RustDesk 实例能接收新的连接参数。用户已恢复的运行实例在 replayd 日志出现 `TCC Allow`。

## 平台范围

CI 验证对应操作系统上的实际程序执行。Android 真实手机/平板的厂商后台策略、不同运营商网络的稳定性、屏幕录制和辅助功能权限、登录前桌面访问依赖具体设备与系统设置。macOS 包尚未获得 Apple 开发者公证，Windows 包尚无 Authenticode 证书。
