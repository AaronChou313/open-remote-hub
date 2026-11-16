# 0.6.0 客户端版本

依据用户提供的《OpenRemoteHub 客户端优先架构重构设计 v1.0》实现，并按用户补充要求完成安装包与项目清理。界面参考用户提供的 FlClash 截图。

## 已实现

- 桌面统一窗口、同账号设备目录、稳定设备身份、目标专用 Ticket 和目标工作区。终端由客户端建立子窗口，关闭界面保留后台。
- 桌面与 Android 使用控制端持有的共享前端资源。API、Cookie、WebSocket、文件和终端走原有 Mesh 网关。
- 可选模块状态与平台依赖检测，新安装默认关闭。已有安装保留入口。缺少依赖提供安装说明。
- Windows ConPTY 会话、输入、尺寸调整、关闭 UI 后重连，以及原生文件上传下载、编辑、复制移动、回收恢复。
- Android 控制端设备目录、应用内工作区、终端、文件选择与下载，以及 RustDesk 调用。
- Cloud 备注、手动地址与上报地址分离、控制端身份。Cloud Web 收敛为元数据后台，Mesh Web 收敛为只读诊断。
- 统一桌面安装、后台、托盘和更新入口。Android 固定正式签名，跨版本保留升级链。
- macOS RustDesk 自启和连接通过 LaunchServices 启动，避免 Python responsible process 导致屏幕采集被 TCC 拒绝。

## 已执行的验证

- Python 全量测试通过 271 项，后续新增 Windows 文件回归测试通过，RustDesk 适配专项 34 项通过。
- 前端交互脚本通过设备选择、错误状态、链路显示、终端路由和未保存编辑保护。增加 Ticket 兑换保留 Android 工作区上下文的回归检查。
- Go 转发、API 测试通过，新增检查本机前端资源与目标 API 的分流，既有测试覆盖 Cookie 和真实 WebSocket 转发。
- Windows CI 已运行打包后的 Agent，验证默认模块关闭、文件上传、文本读取、Range 下载、ConPTY 真实命令输出、尺寸变化及关闭 WebSocket 后重连历史。
- Linux、Intel Mac、Apple Silicon Mac CI 已完成安装包构建，并执行打包 Agent 的模块与文件传输验证。
- 本机已安装 macOS 应用，迁移原有账号与设备身份到用户 LaunchAgent。原生窗口显示同账号 Mac 与 Windows，实际读取本机系统指标及模块依赖状态。
- 真实 Mac 到旧 Windows Agent 已通过目标 Ticket 和 `/api/me`、`/api/system`，链路观察到 P2P。早期原生窗口验证了 Zellij 真实输入、关闭子窗口与重新接入，全部窗口关闭后 Agent 与 Mesh 继续运行。
- Android ARM64 正式签名构建和 lint 通过，APK 已安装到 Android 35 ARM64 模拟器。
- Cloud 已部署元数据更新，HTTPS 健康接口正常，Headscale 运行中。
- 用户修复当前 RustDesk 实例后，本机 replayd 日志出现 `TCC Allow`。新增回归测试验证自启、远程桌面和文件传输的 macOS 命令均经过 LaunchServices。

跨平台 CI 的 Agent 验证覆盖对应系统上的真实程序执行。物理 Android 保活、跨运营商 DERP 以及重启至登录前的桌面访问需结合实际设备权限与网络验证。
