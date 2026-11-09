# 架构

FastAPI 原生部署在宿主机，不将访问宿主信息的后端强行装入容器。静态 HTML/CSS/JavaScript 无前端构建依赖；Node 只用于开发时执行交互测试。

| 模块 | 职责 |
| --- | --- |
| app/file_access.py / files.py | 授权根目录、FD 路径边界、受保护路径、流式传输、并发版本、回收恢复 |
| app/projects.py | 项目记录、只读 Git、预设任务与文件/终端/环境关联 |
| app/environments.py | 主机工具、环境元数据、绑定与明确确认的 venv 创建 |
| app/workspace_store.py | 与系统指标分离的私有 SQLite 元数据和版本比较更新 |
| app/workspace_commands.py | 有界 argv 工具查询，固定环境与 FD 工作目录 |
| static/workspace.js | 文件/项目/环境操作界面，沿用现有原生前端 |
| app/main.py | 系统指标、SQLite 历史、Docker、任务、入口及安全中间件 |
| app/platforms.py | 通用命令边界与 macOS / Linux 服务适配 |
| app/access.py / passwords.py | 持久 Cookie 与密码哈希 |
| app/zellij_sessions.py | 有界会话发现，异常时使用真实进程/保存布局并明确警告 |
| app/zellij_manage.py | 精确目标的会话生命周期管理及删除备份 |
| app/terminal_entry.py | 同名会话复用、创建/恢复、按需准备 Web 服务 |
| app/native_terminal.py | 原生 Zellij 页面与 WebSocket 的同源认证网关 |
| static/sessions.js | 会话卡片与原生终端入口，异步请求守卫 |

终端的持久化、渲染、Tab/Pane 和输入完全交给 Zellij 原生客户端。控制台只列出 Session 并提供生命周期操作和入口，不注册 Tab/Pane 查询或操作 API。Codex 等程序使用普通终端，不在架构中设为特殊 Agent。

删除与停止不同：结束会话会保留布局；删除历史只对已退出会话执行；结束并删除明确中断整会话。删除前备份，再校验实际结果；另一浏览器已删除的目标按幂等成功处理。

Zellij 有可能在 socket 已消失、所有子任务均结束后留下继续写归档的服务进程。仅在这些条件和 PID/create_time/会话名均核验后清理该退出残留，再删除历史。不以“看起来空闲”为由结束任何仍有子任务的进程。

平台扩展通过宿主适配层和通用 Zellij/Docker CLI 接口实现。尚未引入多设备代理或集群抽象。


网关保持浏览器到 Zellij 的原生消息转发，不注入键盘处理器、布局命令或自建终端层。网关到 Zellij 不发送库默认的定时 Ping，避免 0.45.1 对不支持帧的报错；这项兼容处理不被视为旧会话所有黑屏情况的根因修复。

网络入口由 `app/network.py` 统一校验，`ORH_HOST` 配置监听、`ORH_ALLOWED_HOSTS` 配置目标 IP/主机名，HTTP 与原生终端 WebSocket 共用规则。默认 loopback，不接受通配目标地址；严格同源，不信任转发头。Zellij 上游保持 loopback，启动探针跟随绑定地址，便于迁移 macOS/Ubuntu。

DSH 由 `app/dsh.py` 管理已安装官方 CLI，`scripts/dsh_host.py` 作为独立 supervisor 捕获启动认证、遮盖日志并保留后台 Host。`app/dsh_auth.py` 只调用官方 Token 交换，不解析/伪造其签名秘密。`app/dsh_gateway.py` 转发原生 HTTP/流和 typed Remote mux；`scripts/server.py` 在启用时通过两个监听 socket 的实际本地端口分发到控制台/DSH 网关，同一生命周期、不同 Origin。Host/Origin 不参与应用选择。DSH 只接受管理员 Cookie，网关认证与上游凭据分离。桌面 Host 与受管 Web Host 不混同。
