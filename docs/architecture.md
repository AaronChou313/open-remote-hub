# 架构

FastAPI 原生部署在宿主机，不将访问宿主信息的后端强行装入容器。静态 HTML/CSS/JavaScript 无前端构建依赖；Node 只用于开发时执行交互测试。

| 模块 | 职责 |
| --- | --- |
| app/main.py | 系统指标、SQLite 历史、Docker、任务、入口及安全中间件 |
| app/platforms.py | 通用命令边界与 macOS / Linux 服务适配 |
| app/access.py / passwords.py | 持久 Cookie 与密码哈希 |
| app/zellij_sessions.py | 有界会话发现，异常时使用真实进程/保存布局并明确警告 |
| app/zellij_manage.py | 精确目标的会话、Tab、Pane 管理及删除备份 |
| app/terminal_entry.py | 同名会话复用、创建/恢复、按需准备 Web 服务 |
| app/native_terminal.py | 原生 Zellij 页面与 WebSocket 的同源认证网关 |
| app/terminal.py | 只读 Pane 列表与当前屏幕输出 |
| static/sessions.js | 会话列表与 Tab/Pane 详情，异步选择守卫 |

终端的持久化和渲染属于 Zellij。层级为 Session（会话）→ Tab（标签页）→ Pane（终端或插件）。控制台对插件仅作折叠展示，不把状态栏等插件误当成用户任务。Codex 等程序使用普通终端，不在架构中设为特殊 Agent。

删除与停止不同：结束会话会保留布局；删除历史只对已退出会话执行；结束并删除明确中断整会话。删除前备份，再校验实际结果；另一浏览器已删除的目标按幂等成功处理。

Zellij 有可能在 socket 已消失、所有子任务均结束后留下继续写归档的服务进程。仅在这些条件和 PID/create_time/会话名均核验后清理该退出残留，再删除历史。不以“看起来空闲”为由结束任何仍有子任务的进程。

平台扩展通过宿主适配层和通用 Zellij/Docker CLI 接口实现。尚未引入多设备代理或集群抽象。
