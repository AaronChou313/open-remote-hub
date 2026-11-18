# 验证记录

## 0.6.20 增量

本机用户指定的异常会话存在活动进程和 Unix socket，但不响应 ConnStatus。限定到单个 socket 的实际探测确认其他会话响应正常，Zellij 0.45.1 的全局 list-sessions 和管理命令因这个会话阻塞。旧删除路径在先行 save-session 时超时，真实会话生命周期检查也因此失败。

结束操作在原生命令不可用时，依据目标 PID 与创建时间结束其进程树。结束并删除跳过先行保存，保留既有布局备份，并在进程退出后直接清理目标缓存目录。已退出历史的删除独立于其他会话的 IPC。会话进入与生命周期操作共用同名锁。

实际经 Cloud 账号认证调用修复后的正常删除 API，指定异常会话约 4.7 秒完成清理，其他会话的 PID 与创建时间核对一致，列表查询恢复至约 0.01 秒。终端相关非 live 检查通过 17 项。真实 Zellij 测试覆盖创建、重命名、结束、删除历史、恢复、重复删除和结束并删除，另在隔离 socket 目录加入不响应 IPC 的对端后验证删除仍能完成，两项 live 检查通过。

回归同时修复重命名后的进程识别。Zellij 的 --server 命令行保留原名称，重命名后的缓存目录保存 PID 与创建时间，状态发现据此识别同一会话，过期 PID 标记由测试确认不会绑定到复用进程。

## 0.6.19 增量

用户反馈 Android App 配合蓝牙键盘在 Mac 终端输入中文时重复输入历史文本。在已安装 Zellij 0.45.1 的真实 xterm.js 中构造连续中文、组合输入和候选词携带历史上下文的浏览器事件。旧 Process-key IME bypass 在最后一种情况下重复发送“你好世界”并产生额外删除字符，预期输出为“你好世界测试”。移动端改用原生 xterm IME 处理后，同一组序列输出符合预期，桌面既有 bypass 保留。

ORH 的屏幕键盘输入在每次提交后清空上下文，覆盖 compositionend 后才更新 textarea、没有最终 input、取消组合、重复中文、emoji、英文空格、退格和提交键。键盘按钮保留点击前焦点并区分显示与收起。移动版 Zellij 顶栏原有 z-index 高于 ORH 工具栏，输入工具栏改为顶栏下方独立一行，并预留终端显示高度。

相关 Python 检查通过 12 项，终端前端事件回归通过。浏览器使用实际 Zellij xterm.js 复现和验证 IME 序列，尚未使用用户的实体平板与蓝牙键盘完成同一输入法的实机复验。

## 0.6.18 增量

AaronDell 安装的官方 DeepSeek Harness 为 0.2.2-rc.3。实机验证内置 Electron Node 及 ASAR CLI 可以独立启动 Web，无需安装额外 Node。ORH 正常模块入口检测为 supported / ready，启动接口返回 running / managed，认证网关页面返回 200，原生 `/api/remote.mux` WebSocket 建立成功。

实机显式重启 DSH 后，新 Supervisor 正常启动，旧进程退出。随后确认 Windows 终端会话与任务均空闲，重启 Agent，DSH Supervisor PID 保持不变并恢复认证访问。Mac Client 经真实 P2P 通道加载 Windows 的完整原生 DSH 工作台，默认工作区和既有会话加载正常，独立浏览器入口共享 ORH 登录会话。已完成首次预览说明，未发送模型任务。相关 DSH、模块和共享页面回归检查通过。

## 0.6.17 增量

AaronDell 实机确认 Docker Desktop 为当前用户安装，CLI 位于 `%LOCALAPPDATA%/Programs/DockerDesktop/resources/bin/docker.exe`，ORH 启动时的 PATH 尚未包含该目录。修复将实际安装路径同时用于检测和正常 Docker API。Docker CLI 当时返回 Engine 命名管道不存在，界面会明确显示已安装且后台尚未就绪。

RustDesk 1.5.3 实机进程名为 `rustdesk.exe`，原进程筛选遗漏了扩展名。Windows 官方 `--get-id` 成功读取设备 ID，直接访问受保护的本机管道被拒绝。修复后 Windows 使用官方 CLI 和实际直连端口提供状态，安全设置在原生客户端中完成。节点小宝 4.5.3 的 Windows 本地版本与路由 API 均正常返回，复用现有适配并开放 Windows 模块入口。相关后端及共享页面回归检查通过。Mac 与 AaronDell 已安装最终 0.6.17，Windows 返回真实 RustDesk ID、两个用户进程与可用直连端口，节点小宝状态 ready，Docker installed=true 且后台未就绪。通过 Mac Client 的共享工作区实际查看 Windows 的模块状态和远程桌面页面，页面正常显示设备 ID 和进程，未再请求不受支持的 Unix 设置接口。

## 0.6.16 增量

Python 回归通过 304 项，共享前端交互脚本全部通过，Go 全包 race 检查通过。新增检查覆盖模块操作限定作用域、旧 Cloud 绑定登录入口、组件化代理配置保留自定义字段、SSH 配置保留注释，以及软件更新状态与下载。Android 正式签名构建及 lint 通过，Android 35 ARM64 模拟器通过真实 Mesh、Ticket 和账号会话进入已安装 Mac Agent 的共享控制台。

实际页面先复现了“功能管理 → 组网状态 → 其他按钮”失效。原因是全局 `[data-module]` 选择器匹配到 body，操作时替换了整个 body。限定到模块内容区域的按钮后，同一操作序列及进阶功能展开/收起正常。远程桌面图标已补齐线条属性，设置、代理配置和关于页面经过实际渲染检查。

Mac 与 AaronDell 均已安装 0.6.16，长期设备身份和账号绑定保留。Windows 安装后截图确认原生菜单条已移除且标题栏使用 ORH 图标。Windows 控制端经自身 Mesh 网关访问 Mac，DSH 原生页面返回 200，“果壳签到”17861 应用返回 200，远程桌面入口返回控制端本地 RustDesk 转发地址。Windows 的原生独立 DSH 子窗口由窗口创建检查覆盖，其手动点击验收受当前远控工具操作限制。

Mac 实际 DSH 工作台加载完成，页面填充可用高度，现有 DSH supervisor 与 Mihomo 继续运行。旧绑定遗留静态门户登录地址的问题已通过实际 Cloud 登录并返回控制台验证。软件更新页实际读取 GitHub 最新版本并显示结果。

## 0.6.15 增量

拆分本地局域网、节点小宝、网络代理和远程桌面模块，补齐导航图标与注册入口。Cloud 部署已改为开放注册，并实际完成新账号注册与登录后清理测试账号。共享前端交互检查通过，Python 全量检查通过 298 项，相关 46 项检查通过。Go 内部包通过 race 检查，覆盖控制端认证、已保存应用的字节通道和 RustDesk 转发入口。

本机安装版验证 已接续源码版现有 DSH supervisor 认证，实际 Web 工作台加载原生会话与模型界面。迁移过程中原 DSH supervisor、Mihomo broker 和 Mihomo 进程持续运行。Android 正式签名 APK 构建与 lint 通过。Android 35 ARM64 模拟器使用真实账号进入已安装 Mac 的共享控制台。

独立服务访问验证覆盖本机 Host/Origin 转换、本机绝对重定向和应用 WebSocket。使用现有“果壳签到”17861 服务实际读取页面与 33224 字节脚本，均返回 HTTP 200。真实 Windows 控制端通过自身 Mesh 网关访问 Mac，同样读取页面及脚本成功，同时通过 DSH 认证网关，RustDesk 入口返回 Windows 本机 TCP 转发地址。应用通道回归检查覆盖浏览器关闭时的 WebSocket 断开。同页局域网链接、旧导航地址及首次安装 Mihomo 的模块跳转均通过前端回归检查。

macOS ARM64 安装包使用本地可移植 CPython 3.14.8 / OpenSSL 3.5.9 构建，声明最低 macOS 15。本机 Mac 与 AaronDell Windows 已安装 0.6.15，并在最终安装版本再次完成 Windows 到 Mac 的应用、DSH 与 RustDesk 通道检查。其余平台发行构建通过。Android 交互验证范围为 Android 35 ARM64 模拟器。

## 0.6.10 增量

Python 全量检查通过 296 项，另有 12 项真实服务检查按现有设置排除。共享前端交互脚本覆盖设备主入口、模块导航、Mesh TCP 转发、草稿保护和备用访问设置。Go 内部模块通过 race 测试，新增 Ticket 检查确认使用已绑定 Cloud、保持账号错误状态并排除无效设备路径。

macOS 打包 Agent 在独立运行目录执行核心、文件与任务检查。通过安装版交互式恢复命令设置测试密码后，配置备用监听并重新启动，经真实局域网地址访问 Web API 成功，测试过程中该 Agent 的 Mesh 保持关闭。缺失备用接口与 IPv6 配置的回归检查确认本机 IPv4 回环入口继续保留。绑定模式下的本地恢复、密码轮换、Cloud 会话保持和不同账号目录缓存隔离由 API 回归覆盖。

共享页面实际点击验证“我的设备 → 打开控制台”、模块导航、文件页、Mesh 诊断和访问设置。真实 Mesh 到 Windows 的连通性检查返回 P2P 直连。

Android 35 ARM64 模拟器复现了 Java 获取 Cloud Ticket 时的 `SSLHandshakeException connection closed`。Ticket 改为复用现有 Go Cloud 传输后，模拟器通过真实 Mesh、目标 Ticket 和 Cookie 登录，成功打开安装版 Mac Agent 的共享控制台。点击入口改为立即创建控制台页面，在页面内异步准备连接，失败保留错误与重试。Android 发布构建与 lint 通过，Manifest 回归检查保留应用内组网和独立 connectedDevice 前台服务。

网络页同时修复 RustDesk、节点小宝及局域网子页对旧摘要元素的引用。现有 macOS Mihomo 后台与两份机场配置已恢复识别，代理进程与流量保持连续运行。Mihomo 新装流程在隔离 Linux 环境启动实际 broker 与内核，使用临时服务管理适配器。x64 下载使用官方 v1 CPU 基线构建。macOS 菜单栏进程 activation policy 为 accessory，原生窗口为 regular，只有一个进程显示 Dock 图标。

Windows 实机已升级至 0.6.10，设备身份、保存的账号和核心 API 验证通过，安装器与测试任务已清理。Mac 安装版通过后台重启 API 完成实际重启，认证会话保留，随后在共享界面打开 Windows 控制台并显示 P2P 直连。

macOS ARM 的 GitHub 构建节点持续排队后被取消。最终发行包改用 CPython 3.14.8 / OpenSSL 3.5.9 便携运行时，在本机构建并安装验证，最低系统设为 macOS 15。Python 动态库最低系统为 macOS 11。Windows、Linux、macOS Intel 及 Android 的发布任务通过。

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
