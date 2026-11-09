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
- **文件管理**：授权目录浏览、文件名搜索、流式上传/下载与 Range、复制/移动/重命名、回收与恢复、UTF-8 编辑和图片预览。版本冲突阻止覆盖，软链接/硬链接及敏感文件受保护。
- **项目管理**：持久化本地项目记录，识别 Git/技术栈/环境标记，查看状态、分支、提交、工作区及暂存区 Diff；关联文件、终端、环境与预设任务。移除记录不删除项目。
- **开发环境**：Python/Conda/Node/venv 与工具版本、Homebrew 已安装软件查询、环境依赖元数据和项目绑定。确认计划后创建全新项目 venv；不覆盖、不批量安装或自动更新。
- **后台任务**：普通启动命令或 JSON argv，“保存”或“保存并启动”，日志与生命周期管理。仅控制本项目创建并验证身份的进程组；宿主机其他服务只读。
- **DSH 工作台**：通过独立认证入口嵌入本机 DeepSeek Harness 官方 Web，也可独立窗口使用；保留其原生工作区、会话、插件、模型、权限和审批流程。
- 黑白、靛蓝、暗色模式及响应式布局。普通启动直接执行；停止、删除等有一次明确的影响确认；异步操作显示忙碌并防重复提交。

新建会话从当前用户主目录 `~` 启动；恢复会话保留其已保存目录。原生终端在新标签页内完成准备和自动跳转，恢复后不用回控制台确认或刷新。历史程序不使用 `--force-run-commands` 自动重放。已有会话需要允许 Zellij Web sharing；项目新建会话使用独立 `config/zellij.kdl`。

Codex、编辑器和开发服务器都只是用户在普通终端内启动的程序。控制台不自建 AI 聊天引擎、Codex 专用权限、Agent 守护恢复或模型 API；DSH 模块接入官方原生 Web。用户自行运行 `codex` 并管理其配置。

## 认证与安全

密码仅保存为带随机盐的 PBKDF2-HMAC-SHA256 哈希，600,000 次迭代。登录 Cookie 为 HttpOnly / SameSite=Strict，有效期 12 小时；修改密码撤销旧登录。接口检查 Host、来源与 CSRF header，终端 WebSocket 还检查管理员登录并持续验证撤销。

Zellij 网关只访问固定的本机端口（默认 8082）。内部 Zellij Token/Cookie 不会发送给浏览器，不提供任意 URL 或 RPC 转发。WebSocket 只转发官方原生客户端，不提供额外 Shell 或自建 PTY。

管理员的交互终端及任务具备当前本机账户权限。支持显式开启局域网/私有组网访问；不内置 TLS/MFA 或多用户隔离。保持默认本机监听时，也可使用已配置的 SSH 转发：

```sh
ssh -N -L 8765:127.0.0.1:8765 USER@HOST
```

## 局域网与异地组网

默认只监听本机。编辑项目根目录 `.env`，不需要修改源码：

```dotenv
ORH_HOST=0.0.0.0
ORH_PORT=8765
ORH_ALLOWED_HOSTS=192.168.1.20,100.66.1.2,100.66.1.4,server.local
ORH_ZELLIJ_PORT=8082
```

将示例地址替换为实际主机的局域网 IP、组网映射 IP 或可解析主机名。`ORH_HOST` 是本机监听地址：`127.0.0.1` 仅本机，`0.0.0.0` 为所有 IPv4 接口，也可指定本机单个 IP；虚拟映射 IP 若不在本机网卡上，不能用作监听地址。IPv6 可用 `::`（是否兼听 IPv4 取决于平台）。

`ORH_ALLOWED_HOSTS` 是浏览器地址栏允许使用的目标地址，逗号分隔，不含协议、端口、CIDR 或通配符；不是客户端 IP 列表。`localhost`、`127.0.0.1`、`::1` 始终允许，指定的单个监听 IP 也自动允许。所有入口使用 `ORH_PORT`，端口映射需保持相同外部端口。新增地址或迁移主机时修改这个列表即可，不自动信任所有本地网卡、组网设备或任意 Host。

```sh
./scripts/stop.sh
./scripts/start.sh
```

浏览器打开 `http://目标地址:8765/`，使用原密码登录，终端仍通过同一地址转发，不需要开放 Zellij 的 8082 端口。不同 IP/主机名是不同的浏览器登录站点，首次切换地址需各登录一次；同一地址内进入终端无需再次登录。首次设置密码仍只能从本机 localhost 页面或 `scripts/password.py` 完成。

HTTP 与 WebSocket 共享目标地址白名单，并要求有 Origin 的请求与当前入口严格同源；配置多个地址不代表它们可以相互跨源调用。服务不信任客户端提供的 `X-Forwarded-*`。当前示例为 HTTP，请使用可信局域网或已加密的私有组网；不要为此在路由器开启公网端口转发。HTTPS 反向代理需要另行明确可信代理和证书配置。

## DeepSeek Harness / DSH

支持本机已安装的 DSH 0.2.x，实际验证 `0.2.2-rc.1`。DMG 自带不可变 CLI 与运行时，`npx` 使用 npm 缓存，它们不会互相更新；检测会优先选择较新版本，同版本优先 DMG 附带 CLI，不静默使用 0.1 旧缓存。也可在本机 `.env` 明确指定 `ORH_DSH_BIN`（可执行文件或 `lib/bin.js`），不会自动安装/升级 DSH。

```dotenv
ORH_DSH_ENABLED=1
ORH_DSH_GATEWAY_PORT=8767
ORH_DSH_PORT=9741
# ORH_DSH_BIN=/Applications/DeepSeek Harness.app/Contents/Resources/runtime/cli/bin/dsh
# ORH_DSH_HOME=/Users/you/.dsh
```

重启控制台后进入侧栏“DSH 工作台”。首次未运行时点击“启动并进入”；同一个本机受管进程会直接复用，不重复启动。原始 DSH 固定监听 `127.0.0.1:9741`，认证网关跟随 RemoteHub 的监听地址，在 `8767` 提供官方根路径页面与接口。访问局域网/组网时需能访问这两个控制台端口（默认 8765、8767）；不需要把 9741 暴露给远端。入口主机白名单和 Origin 规则继续生效。

浏览器登录 RemoteHub 后，其 HttpOnly Cookie 可用于同一主机的 DSH 网关，用户无需另输 DSH Token。网关只允许管理员；HTTP 与 `/api/remote.mux` WebSocket 均检查登录和来源，连接期间持续检查撤销，发送/接收每帧也重新检查权限。原生认证通过官方启动 URL 交换 Cookie 完成，Token/Cookie 仅存本机 `.runtime/dsh-auth.json`（0600），可通过原生流程续期，不把上游凭据或 Set-Cookie 发给浏览器；日志中的启动 Token 被遮盖。原始 JS/插件 bundle 字节不改写，网关只在 HTML 启动前补齐 HTTP 环境缺失的标准 `crypto.randomUUID`（浏览器安全随机数实现）。

DSH 官方前端使用根路径和自身插件加载器，因此采用独立端口、独立浏览器 Origin，嵌入控制台并提供“独立窗口”。其目录选择使用官方 browse 插件，通过本项目的 `config/dsh-web.patch.yml` 追加启动 overlay，不修改用户 profile 或已安装包；避免远程操作时在 Mac 上弹出本地 OS 对话框。DSH 的主题与插件仍由其原生生态控制。

**实例边界**：此模块使用本机 DSH 的官方 **Web profile**，默认共用 `~/.dsh` 用户根目录。桌面版运行在 Desktop profile 和自己的 Host 中；共享数据根目录不代表共享执行中的进程、内存或任务。控制台不会接管、重启桌面版，也不伪装成能无缝接续桌面版正在运行的任务。已有其他 Web 实例占用指定内部端口时不冒认或强行结束。

DSH 与独立认证日志 supervisor 在浏览器或控制台退出后继续运行；控制台重启会按 PID/创建时间/启动脚本校验复用它。整机重启后旧计算进程已不存在，需重新启动 Web Host，再由 DSH 自己恢复持久化记录。关闭浏览器不等于停止 Host；具体模型任务的断线行为仍以 DSH 自身实现为准。`.runtime/dsh.log`、认证状态、启动计划均为私有文件，没有远程原始日志/令牌下载入口。

未执行真实模型计费请求；复杂任务、第三方插件、桌面专用能力、账号 OAuth 与实体手机输入法仍需按实际使用验收。Native UI 不同版本可能有兼容变化；新增版本不能仅凭页面加载即视为全部验证通过。

## 文件、项目与开发环境

本机 `.env` 设置授权范围，重启控制台后生效。例如：

```dotenv
# 显式授权主机根目录；也可以改为项目目录的 JSON 数组
ORH_FILE_ROOTS=["/"]
ORH_MAX_UPLOAD_MB=2048
```

新安装默认为 `[]`，不开放文件。`["/"]` 允许以当前账户权限浏览主机；系统目录只读，不能绕过 macOS 隐私授权、Linux 权限或挂载权限。`.env*`、私钥、`.ssh`、`.config`、`.codex`、`.runtime`、`.git`、浏览器/系统凭据目录等仍受保护；普通 `node_modules` 可浏览。受保护项显示具体原因，系统目录仅可读取。保护规则不是自动识别所有文件中的秘密，未知名称的敏感数据应放到受保护目录，或缩小授权范围。

文件页首次进入当前账户主目录，并提供“主目录”快捷入口。可切换隐藏文件显示（点开头的名称）、名称/修改时间/大小/类型排序及升降序，目录优先；筛选和排序在分页前执行。文件夹“操作”打开居中菜单，避免滚动到列表底部。文件页选择目录后可添加为项目或打开终端。**新会话**使用选定目录；选择已有/恢复会话时保留原工作目录及任务，不注入 `cd` 或重排 Pane。项目页保存终端关联并可进入原生客户端。

文件删除移入同级 `.remotehub-trash`，可用当前目录的“回收记录”恢复；恢复不覆盖现有目标。没有自动清空、永久删除或自动清理策略。含受保护文件的整目录复制、移动、删除会被拒绝。复制上限 1 GiB / 10000 条目，跨文件系统移动不自动降级为复制后删除；请先复制、核验，再明确删除。默认上传上限 2 GiB，可调至最高 8 GiB；上传只创建新文件，不覆盖同名文件。下载保持打开的文件描述符分块传输，支持单个 HTTP Range，不生成内存中的整文件副本。

文本编辑限 UTF-8、1 MiB，保存前确认目标并核验文件版本；冲突时保留编辑内容，不静默覆盖。文本/Markdown/代码以纯文本呈现，PNG/JPEG/GIF/WebP 可预览；HTML/SVG 不执行，PDF/视频/Office 文件先下载。目录列表最多扫描 10000 条、每页 200 条；文件名搜索最多扫描 10000 条或 3 秒，返回最多 100 条，并标注截断。

项目页自动发现 `~/Projects` 的直接子目录，并将关联信息保存在私有 `workspace.sqlite3`。可用 `ORH_PROJECTS_DIR` 指定项目父目录，该目录仍须位于授权范围。隐藏自动发现的项目后，后续扫描不会重复添加；手动添加可重新纳入。Git 仅只读查询，不切分支、提交、拉取或推送；禁用 fsmonitor/外部 Diff/textconv，并过滤受保护文件的 Diff。Git 工作树元数据必须位于授权范围，符号链接元数据不支持。

项目可运行受支持的 npm dev/start/build/test（含前后置脚本展示）、pytest 或 Django 开发任务；执行前展示实际参数、目录与脚本，确认后复用“任务与服务”的日志和进程管理。任务会执行项目代码，并不代表代码经过安全审计。环境绑定影响后续生成的预设，不改变已运行任务；Node 绑定使用对应 Node/npm，Python 绑定使用对应解释器，Conda 的 npm 任务使用 `conda run`。其他命令仍在原任务页显式配置。

环境页检测主机 PATH 上的工具、Conda 注册环境和已添加项目的 `.venv`/`venv`。Python 依赖读取 `.dist-info`/Conda JSON 元数据，避免为了检查而执行项目解释器、pip 或 `.pth`。可创建 `.venv`/`venv`：先展示计划，确认后排他创建目录，本机 Python 自带的 pip 随 venv 初始化，不联网安装包、不覆盖、不自动绑定；失败保留部分目录供检查，不会偷偷删除重建。未实现 Conda 环境创建、版本切换、包安装/更新或环境删除。Ubuntu 软件查询走只读 dpkg 适配，尚待实机验收。

文件路径采用目录 FD 与 `O_NOFOLLOW` 逐级访问，上传/复制先私有暂存再原子无覆盖发布。macOS/Linux 使用原子无覆盖重命名；其他平台失败关闭。版本检查和进程锁保护控制台内并发操作；这不是 OS 沙箱，不能阻止拥有相同系统账户权限的本机进程移动已打开目录，也不提供对外部编辑器写入的文件系统级事务快照。

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
node tests/workflow-ui.mjs         # 原有前端交互测试
node tests/workspace-ui.mjs        # 文件竞态、转义、未保存编辑保护
node --check static/app.js
node --check static/sessions.js
```

显式的本机验证会创建自己的测试会话并清理，需要 Zellij Web 服务在线。不会操作已有业务会话：

```sh
.venv/bin/pytest -m live tests/test_terminal_entry.py tests/test_zellij_management.py -q
```

[架构](docs/architecture.md) · [验证与限制](docs/validation.md)
