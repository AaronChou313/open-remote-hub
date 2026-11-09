# OpenRemoteHub

原生运行的个人服务器控制台：系统状态、Docker 容器、Zellij 终端和自主管理的后台任务。默认只监听 localhost，使用自设密码登录。

## 启动

需要 Python 3.11+。Docker 和 Zellij 使用当前用户已安装的 CLI；不修改 OrbStack 或用户的全局配置。

```sh
./scripts/install.sh
./scripts/start.sh
```

访问 [控制台](http://127.0.0.1:8765/)，首次在本机设置密码。后续通过同一个登录进入官方 Zellij Web Client，无需另输 Token。

```sh
./scripts/stop.sh                 # 仅停止控制台，保留终端和任务
.venv/bin/python scripts/password.py # 本机隐藏输入重设密码
```

## 功能

- **系统概览**：真实 CPU、内存、磁盘、网络和进程；SQLite 保留 7 天轻量历史。
- **Docker**：每容器一张卡片，状态、资源、配置端口、详情和日志；启动、停止、重启。沿用当前 Docker context，不自动清理镜像、卷或网络。
- **终端会话**：每会话一个入口，创建并进入、恢复并进入、重命名、结束、删除历史、结束并删除。控制台不查询或管理 Tab/Pane，用户在原生终端中自行操作。
- **会话删除**：删除前保存本机私有备份，删除后校验；不使用全局 kill/prune。退出历史与运行会话明确区分。
- **后台任务**：普通启动命令或 JSON argv，“保存”或“保存并启动”，日志与生命周期管理。仅控制本项目创建并验证身份的进程组；宿主机其他服务只读。
- 黑白、靛蓝、暗色模式及响应式布局。普通启动直接执行；停止、删除等有一次明确的影响确认；异步操作显示忙碌并防重复提交。

原生终端在新标签页内完成准备和自动跳转，恢复后不用回控制台确认或刷新。历史程序不使用 `--force-run-commands` 自动重放。已有会话需要允许 Zellij Web sharing；项目新建会话使用独立 `config/zellij.kdl`。

Codex、编辑器和开发服务器都只是用户在普通终端内启动的程序。控制台没有 AI 助手、Codex 专用权限、Agent 守护恢复或模型 API。用户自行运行 `codex` 并管理其配置。

## 认证与安全

密码仅保存为带随机盐的 PBKDF2-HMAC-SHA256 哈希，600,000 次迭代。登录 Cookie 为 HttpOnly / SameSite=Strict，有效期 12 小时；修改密码撤销旧登录。接口检查 Host、来源与 CSRF header，终端 WebSocket 还检查管理员登录并持续验证撤销。

Zellij 网关只访问固定的本机端口（默认 8082）。内部 Zellij Token/Cookie 不会发送给浏览器，不提供任意 URL 或 RPC 转发。WebSocket 只转发官方原生客户端，不提供额外 Shell 或自建 PTY。

管理员的交互终端及任务具备当前本机账户权限。当前版本不提供公网监听开关、TLS/MFA 或多用户隔离。远程使用可通过已配置的 SSH 转发：

```sh
ssh -N -L 8765:127.0.0.1:8765 USER@HOST
```

## 部署与维护

配置见 `.env.example`。安装只创建项目虚拟环境、配置和运行目录，不执行 sudo/brew，也不下载容器镜像。

```sh
.venv/bin/python scripts/launchd.py install
.venv/bin/python scripts/launchd.py uninstall
```

macOS 使用用户级 launchd，在用户登录后启动控制台。Ubuntu 有 `deploy/openremotehub.service` 用户 systemd 模板；平台边界已区分，Ubuntu 尚未实机验收。

`.runtime/` 存放密码哈希、认证/历史数据库、任务定义、日志和会话删除备份；必须保持私有，不能提交。日志没有完整在线轮换，持续高输出任务应自行配置轮换。会话删除备份默认保留，按需由用户归档或清理。

旧版专用 `codex-agent` 会话保留为普通会话，本次不打断它的已有进程；旧进程原先的启动参数直到它退出前仍然有效。兼容入口 `scripts/agent_run.py` 仅用于旧保存布局再次启动时执行普通 Codex（可继续原历史），不添加权限参数。旧 AI 数据只保留在本机私有运行目录，不再被控制台加载或自动恢复。

## 开发与验证

```sh
.venv/bin/pip install -r requirements-dev.txt
.venv/bin/pytest -q                 # 默认仅单元/安全测试，不操作本机服务
node tests/workflow-ui.mjs         # 前端交互测试，无浏览器/主机变更
node --check static/app.js
node --check static/sessions.js
```

显式的本机验证会创建自己的测试会话并清理，需要 Zellij Web 服务在线。不会操作已有业务会话：

```sh
.venv/bin/pytest -m live tests/test_terminal_entry.py tests/test_zellij_management.py -q
```

[架构](docs/architecture.md) · [验证与限制](docs/validation.md)
