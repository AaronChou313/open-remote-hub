# OpenRemoteHub

原生运行的个人服务器控制台，管理系统状态、Docker、Zellij、文件、项目与本地服务，并集中保存 Web 应用入口。默认只监听 localhost，使用自设密码登录。

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
- **远程连接**：统一展示 Tailscale 组网与 RustDesk 桌面服务状态，提供组网设备、直连/中继、Ping、网络诊断、连接与断开、DNS/子网路由/入站拦截/出口节点设置，以及 RustDesk ID、密码、客户端配置和原生连接入口。
- **我的应用**：卡片式 Web 入口，支持添加、编辑、移除、分组和搜索。可保存当前主机的协议、端口、路径，访问地址随控制台当前主机名变化；也可保存完整自定义 URL。点击直接打开服务。
- **本地服务**：合并用户与系统 launchd / systemd 服务、TCP 监听进程、Docker 已发布端口和已有项目进程。展示 PID、命令、运行时间、绑定地址及可读取日志，支持搜索和类型筛选。识别 Web / HTTP 后提供访问及添加应用入口，普通服务保持只读。
- **DSH 工作台**：通过独立认证入口嵌入本机 DeepSeek Harness 官方 Web，也可独立窗口使用；保留其原生工作区、会话、插件、模型、权限和审批流程。
- 黑白、靛蓝、暗色模式及响应式布局。普通启动直接执行；停止、删除等有一次明确的影响确认；异步操作显示忙碌并防重复提交。

新建会话从当前用户主目录 `~` 启动；恢复会话保留其已保存目录。原生终端在新标签页内完成准备和自动跳转，恢复后不用回控制台确认或刷新。历史程序不使用 `--force-run-commands` 自动重放。已有会话需要允许 Zellij Web sharing；项目新建会话使用独立 `config/zellij.kdl`。

Codex、编辑器和开发服务器都只是用户在普通终端内启动的程序。控制台不自建 AI 聊天引擎、Codex 专用权限、Agent 守护恢复或模型 API；DSH 模块接入官方原生 Web。用户自行运行 `codex` 并管理其配置。

“本地服务”每 5 秒刷新运行状态，本机 HTTP / HTTPS 识别缓存 90 秒，点击刷新可重新识别。发现范围包括服务管理器登记项及 TCP 监听进程，按当前宿主账户权限读取。Web 判断使用本机 HTTP HEAD，401、404、405 等 HTTP 响应也表示存在 HTTP 服务。完整业务页面路径可在应用设置中调整。

“我的应用”按用户选择保存直连地址。远程访问时，目标服务需自行开放局域网监听及对应端口；仅绑定 127.0.0.1 / ::1 的服务显示“仅本机”。项目预设仍在项目页面运行，运行输出可在“本地服务”查看；独立快捷任务表单已移除，已有任务记录继续保留。

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
ORH_FILE_POLICY=unrestricted
ORH_MAX_UPLOAD_MB=2048
```

新安装的目录范围默认为 `[]`。`ORH_FILE_POLICY=unrestricted` 配合 `["/"]` 开放当前系统账户可访问的目录，取消控制台对系统目录写入、凭据目录、隐藏文件及硬链接的额外限制。目录和文件软链接可直接打开，链接目标也须位于配置的目录范围内。复制链接会保留链接本身，移动、重命名和回收操作作用于链接本身；通过文件链接编辑时更新实际文件并保留链接。

`ORH_FILE_POLICY=protected` 是新安装的默认策略，系统目录只读，`.env*`、私钥、`.ssh`、`.config`、`.codex`、`.runtime`、`.git`、浏览器/系统凭据目录及链接受保护。两种策略均使用现有登录认证、操作确认、文件版本检查和流式传输。设备节点、Socket 等特殊对象不支持文件编辑和传输。

### macOS 目录隐私授权

下载、桌面、文稿、网络卷和移动卷可能触发 macOS 本机隐私授权。要避免远程访问时逐个目录等待确认，请由用户在 **系统设置 → 隐私与安全性 → 完全磁盘访问权限** 添加并启用运行 RemoteHub 服务的 Python.app。该授权需要用户在 Mac 上操作，应用代码无法自行授予。[Apple 文件访问说明](https://support.apple.com/en-ie/guide/security/secddd1d86a6/web)

当前 launchd 使用项目虚拟环境的 Python。可在项目目录执行以下命令，查找实际 Python.app 路径。点击系统设置中的“+”，在文件选择器按 `⌘⇧G` 粘贴输出路径并添加。

```sh
.venv/bin/python -c 'from pathlib import Path; import psutil; print(Path(psutil.Process().exe()).parents[2])'
```

授权后重启控制台并重新访问目录。后续更换 Python 安装路径时需检查对应授权。文件所有者、ACL、只读卷及 macOS 系统完整性保护仍由操作系统执行，Linux 使用服务账户的常规文件权限。

```sh
./scripts/stop.sh
./scripts/start.sh
```

文件页首次进入当前账户主目录，并提供“主目录”快捷入口。可切换隐藏文件显示（点开头的名称）、名称/修改时间/大小/类型排序及升降序，目录优先；筛选和排序在分页前执行。文件夹“操作”打开居中菜单，避免滚动到列表底部。文件页选择目录后可添加为项目或打开终端。**新会话**使用选定目录；选择已有/恢复会话时保留原工作目录及任务，不注入 `cd` 或重排 Pane。项目页保存终端关联并可进入原生客户端。

文件删除移入同级 `.remotehub-trash`，可用当前目录的“回收记录”恢复；恢复不覆盖现有目标。没有自动清空、永久删除或自动清理策略。`protected` 模式下，含受保护文件的整目录复制、移动、删除会被拒绝。复制上限 1 GiB / 10000 条目，跨文件系统移动不自动降级为复制后删除；请先复制、核验，再明确删除。默认上传上限 2 GiB，可调至最高 8 GiB；上传只创建新文件，不覆盖同名文件。下载保持打开的文件描述符分块传输，支持单个 HTTP Range，不生成内存中的整文件副本。

文本编辑限 UTF-8、1 MiB，点击保存直接核验文件版本并写入；冲突时保留编辑内容，不静默覆盖。文本/Markdown/代码以纯文本呈现，PNG/JPEG/GIF/WebP 可预览；HTML/SVG 不执行，PDF/视频/Office 文件先下载。目录列表最多扫描 10000 条、每页 200 条；文件名搜索最多扫描 10000 条或 3 秒，返回最多 100 条，并标注截断。

项目页自动发现 `~/Projects` 的直接子目录，并将关联信息保存在私有 `workspace.sqlite3`。可用 `ORH_PROJECTS_DIR` 指定项目父目录，该目录仍须位于授权范围。隐藏自动发现的项目后，后续扫描不会重复添加；手动添加可重新纳入。Git 仅只读查询，不切分支、提交、拉取或推送；禁用 fsmonitor/外部 Diff/textconv，并过滤受保护文件的 Diff。Git 工作树元数据必须位于授权范围，符号链接元数据不支持。

项目可运行受支持的 npm dev/start/build/test（含前后置脚本展示）、pytest 或 Django 开发任务；执行前展示实际参数、目录与脚本，确认后复用“任务与服务”的日志和进程管理。任务会执行项目代码，并不代表代码经过安全审计。环境绑定影响后续生成的预设，不改变已运行任务；Node 绑定使用对应 Node/npm，Python 绑定使用对应解释器，Conda 的 npm 任务使用 `conda run`。其他命令仍在原任务页显式配置。

环境页检测主机 PATH 上的工具、Conda 注册环境和已添加项目的 `.venv`/`venv`。Python 依赖读取 `.dist-info`/Conda JSON 元数据，避免为了检查而执行项目解释器、pip 或 `.pth`。可创建 `.venv`/`venv`：先展示计划，确认后排他创建目录，本机 Python 自带的 pip 随 venv 初始化，不联网安装包、不覆盖、不自动绑定；失败保留部分目录供检查，不会偷偷删除重建。未实现 Conda 环境创建、版本切换、包安装/更新或环境删除。Ubuntu 软件查询走只读 dpkg 适配，尚待实机验收。

文件路径采用目录 FD 与 `O_NOFOLLOW` 逐级访问，`unrestricted` 模式先解析链接、核验目标范围再打开目录 FD；递归复制保留链接而不递归进入链接目标。上传/复制先私有暂存再原子无覆盖发布。macOS/Linux 使用原子无覆盖重命名；其他平台失败关闭。版本检查和进程锁保护控制台内并发操作；这不是 OS 沙箱，不能阻止拥有相同系统账户权限的本机进程移动已打开目录，也不提供对外部编辑器写入的文件系统级事务快照。

## 代理与网络

支持两种连接方式。未安装独立服务时可连接已有 Clash / Mihomo 控制器。安装独立服务后，RemoteHub 通过仅当前 OS 用户可访问的 Unix Socket 管理自己的 Mihomo，不向局域网公开内核管理接口。

### 安装与迁移

```bash
# 首次下载，核对官方 GitHub release asset SHA-256，不修改现有代理
python3 scripts/proxy_setup.py download
# macOS 预备测试。仅回环端口，TUN 关闭，不修改系统代理或 DNS
python3 scripts/proxy_setup.py stage
# 验证后安装一次专用系统服务。sudo 密码由用户在主机终端输入
sudo /usr/bin/python3 scripts/proxy_setup.py install
```

安装服务不关闭 Clash，首次安装是空配置且代理停止。Mac 使用独立 launchd LaunchDaemon，登录前也可运行；安装的程序和内核数据由 root 持有。浏览器和 RemoteHub 自身重启不影响内核。Linux 提供同一 broker 的 systemd 安装路径，命令为 `sudo python3 scripts/proxy_setup.py install`，尚未完成真实 Linux / TUN 验收。不要把用户目录中的 Python 代码直接作为 root 的长期服务执行。

切换步骤只需一次：在“代理与网络”导入机场提供的 **Clash / Mihomo YAML 订阅 URL** 或配置文件，点击“使用配置”；手动关闭 Clash 的 VPN 连接；点击“启动代理”。没有配置或 Clash VPN 仍连接时拒绝启用。不要同时运行多个 TUN 客户端。原 Clash 的配置和开机设置不会被更改，切换后需自行关闭其自动连接。

回退时先在 RemoteHub 点击“停止代理”，再启动原 Clash。若网页不可达，可在主机执行 `python3 scripts/proxyctl.py stop`。这只关闭 RemoteHub 的 TUN，保留配置与后台内核。`status` 检查状态，`start` 启用，`open` 打开本机网页。所有 CLI 控制均凭当前 OS 用户的 Socket 权限，不需要在命令行保存控制台密码。

### 日常操作

- 机场配置卡片按名称排序，可搜索、导入 URL / YAML 文件 / 粘贴 YAML、使用配置、更新订阅、重命名、更换订阅地址、移除及导出。
- 内置 YAML 编辑器可修改节点、策略组、规则、DNS 等内容，保存前调用实际内核检查。当前配置的更新和编辑会同步应用，失败回退到上一份运行配置；并发修改需刷新。订阅 URL、YAML 和恢复副本保存在 `.runtime/proxy/` 的私有文件中，不提交 Git。导出的 YAML 含节点凭据，只有管理员可读。
- 策略与节点页按分组展开全部节点，支持分组折叠、搜索、默认 / 名称 / 延迟排序。点击节点或模式直接切换，无下拉选择、额外提交或确认。Selector 可直接选择；URLTest / Fallback 可手动固定节点并一键恢复自动。单节点、整组和全部节点均可测速，批量去重、最多 4 个并发、实时进度并可取消，超时与未测速明确区分，不把失败显示为 0ms。规则模式显示默认路由链，GLOBAL 组收起后置并注明仅在全局模式下生效。节点选择由 Mihomo cache 持久化。规则可筛选；内核日志以有界文本显示并隐藏 URL / UUID。
- 停止代理只关闭 TUN，HTTP / SOCKS 回环入口仍就绪。重启内核会中断它自己的连接。启用状态、选中配置和模式跨服务重启保留；重启时发现 Clash VPN 活跃，会保持新 TUN 关闭。内核异常退出后 broker 会尝试恢复。
- Mac 本机与远程设备使用同一个网页。无需菜单栏常驻进程，界面和配置管理可沿用于 Linux。

订阅下载逐跳校验目的地址并固定解析后的公网 IP，保留 TLS 主机校验，禁止访问回环 / 内网服务。遇到 Clash / Mihomo Fake-IP DNS 时用固定 DoH 解析器 `1.1.1.1` 查询真实公网 IP，只提交订阅主机名，不提交 URL 路径或令牌。限制 3 MiB、重定向次数与超时；不接受纯节点 URI / Base64，需要机场的 Clash 格式订阅。定时订阅更新暂未实现，使用“更新订阅”。

### 网络与权限边界

独立内核固定 mixed port `127.0.0.1:7891`、DNS listener `127.0.0.1:1054`、带私有密钥的 controller `127.0.0.1:19090`，控制台使用用户私有 Socket；导入配置不能覆盖这些入口或创建额外 listeners。服务以 TUN 接管主机流量，不写入 macOS HTTP/HTTPS/SOCKS 系统代理设置。TUN 使用 `dns-mode: native` 接管系统 DNS，停止 TUN 时由内核恢复原 DNS，避免局域网 DNS 请求绕过 TUN 劫持。TUN 与“全局”出站模式是不同概念。

默认从 TUN 路由排除 `127/8`、`10/8`、`172.16/12`、`192.168/16`、`100.64/10`，保护局域网、容器私网和异地组网的直接可达性；具体网络仍需切换后现场验收。Provider 支持 HTTP / inline，缓存路径由服务管理，不支持读取任意本地 Provider 文件。其他高级设置可通过 YAML 编辑；不等同于复刻所有 Clash 客户端的特有功能。

已有控制器兼容配置仍可使用（显式设置优先于独立服务）：

```dotenv
# Unix Socket 或带端口的本机回环 HTTP(S) URL，二选一
# ORH_CLASH_SOCKET=/absolute/path/to/clash.sock
# ORH_CLASH_URL=http://127.0.0.1:9090
# ORH_CLASH_SECRET=your-controller-secret
```

模式 / 节点变更只作用于已有客户端的运行实例，持久化由原客户端管理。只读账号不能写入、导出敏感配置或执行测速；所有写操作沿用认证、同源校验、角色检查与审计。[Mihomo API 文档](https://wiki.metacubex.one/api/)

## Web 终端复制、粘贴与手机输入

终端右上角“剪贴板”提供快捷键说明、图片上传和最近选中文字。Web Client 原先直接调用 `navigator.clipboard` 写入选区，局域网 / 组网 HTTP 地址通常缺少该接口；控制台现在提供浏览器旧式复制回退，并区分“已复制”与“已发送复制请求”。旧式接口无法可靠核验系统剪贴板是否更新，浏览器限制下可点“复制”，再按 `Ctrl+C` / `⌘C`，或在手机上长按选中文字复制。受信任 HTTPS / 本机安全上下文可使用标准剪贴板接口。[浏览器剪贴板要求](https://developer.mozilla.org/en-US/docs/Web/API/Clipboard/writeText)

| 操作 | Windows / Linux 浏览器 | Mac 浏览器 |
| --- | --- | --- |
| 复制终端选区 | 鼠标拖选自动尝试复制，或 `Ctrl+Shift+C` | 鼠标拖选自动尝试复制，或 `⌘C` |
| 粘贴文字 | `Ctrl+V` / `Ctrl+Shift+V` | `⌘V` |
| 粘贴剪贴板图片 | `Ctrl+V` | `⌘V` |
| 中断程序 | `Ctrl+C` | `Ctrl+C` |
| Zellij 锁定 / 解锁（默认配置） | `Ctrl+G` | `Ctrl+G` |

`Ctrl+C` 在终端内仍用于中断，需在复制回退窗口的文字选区中使用它复制。按住 Shift 拖选可以使用 xterm 本地选区。Zellij 的 `copy_command "pbcopy"` 会写到服务端 Mac 的剪贴板，远程复制应通过浏览器剪贴板通道。

浏览器真实粘贴事件带有图片时，控制台将 PNG / JPEG / WebP 图片上传到 Mac 的 `.runtime/terminal-attachments/`（单张 20 MiB），并通过原生终端的 paste 接口插入带引号的绝对路径；不会附带回车。可在 Codex 输入区继续输入问题，检查图片附件后再提交。也可通过“剪贴板 → 上传图片”选择图片。图片文件保留供任务继续读取，可在文件管理器中手动清理。容器中的程序需要容器可访问的路径。

Codex 的原生图片快捷键读取运行 Codex 的主机剪贴板。远程设备的系统剪贴板需要浏览器上传通道，普通终端按键不会自动传输图片；也可显式使用 `codex -i /path/to/image.png`。[Codex 图片输入说明](https://learn.chatgpt.com/docs/image-inputs?surface=cli)

Zellij 0.45.1 官方移动端输入使用 password 控件，并在每次触摸后重新聚焦，影响 iPhone 中文输入和滑动查看。网关针对已识别的实现替换为支持 composition 的隐藏 textarea，默认关闭软键盘，通过右上角“键盘”按钮或原生键盘按钮显式切换。拼音候选阶段不发送内容，确认后一次发送最终中文，避免重复提交或丢掉重复字符。滑动继续使用原生 Zellij 手势。升级后若无法识别代码结构则保留新版实现，并在说明窗口标记尚未匹配。

网关只修改移动输入适配段并更新对应 app.js 的 SRI，其余终端库保持原字节。剪贴板兼容层通过独立 JS/CSS 加载。手机宽度布局、中文 composition 事件和真实桌面浏览器图片粘贴已测试；实体 iPhone 键盘语言切换、Safari 触摸手势及系统剪贴板仍需实体设备验收。

## 远程开发与 ROS 2 工作区

文件页和项目详情页提供“用 VS Code 打开”，点击后由浏览器调用访问设备上安装的 VS Code，通过 Remote - SSH 打开 Mac / Linux 主机的目录。默认使用当前浏览器访问的主机地址与服务账户用户名，支持在局域网和私有组网地址之间切换。访问设备需安装 VS Code、OpenSSH 客户端及 Microsoft Remote - SSH 扩展，第一次连接由 VS Code 完成 SSH 主机确认和账户 / 密钥认证。主机需要已启用 SSH 服务。[VS Code 官方说明](https://code.visualstudio.com/docs/remote/ssh)

可以在主机 `.env` 指定连接用户名或客户端的 SSH 别名，修改后重启控制台。

```dotenv
# 默认使用服务账户用户名
# ORH_SSH_USER=aaron
# 可选，覆盖默认连接地址。此别名需在访问设备的 SSH config 中存在。
# ORH_VSCODE_SSH_AUTHORITY=mac-mini
```

自定义 SSH 端口、跳板机和通过 localhost 转发访问控制台时，使用访问设备上配置好的 SSH 别名。例如在访问设备 `~/.ssh/config` 中配置以下内容，再将控制台的 `ORH_VSCODE_SSH_AUTHORITY` 设为 `mac-mini`。

```sshconfig
Host mac-mini
    HostName 100.66.1.4
    User aaron
    Port 22
```

“上传文件”支持多选，“上传文件夹”保留所选目录名及普通文件的子目录结构，自动创建缺失目录。上传进度、取消和失败项重试在居中窗口中完成。同名文件保留原内容并列入失败项；重试只处理失败和未上传的文件，每个失败文件从头传输。浏览器页面关闭后上传会停止，已完成的文件保留。浏览器文件选择器不提供空目录和软链接元数据，这两项不随文件夹上传传输；可在主机终端使用 Git 获取完整仓库。

当前 ROS 2 环境已将 `/Users/aaron/Projects/ros2_ws` 绑定到容器 `/workspaces/ros2_ws`。在文件页进入 `/Users/aaron/Projects/ros2_ws/src` 后上传算法文件夹，容器会看到同一份源码。也可从项目终端执行以下命令，替换示例仓库地址和包名。

```sh
cd ~/Projects/ros2_ws
git clone <仓库地址> src/<仓库目录>
./ros deps
./ros build --packages-up-to <ROS包名>
./ros exec ros2 run <ROS包名> <节点名>
```

`./ros deps` 会按项目依赖执行安装，由用户在终端手动运行。VS Code 通过 Remote SSH 打开 `ros2_ws` 后，安装 Dev Containers 扩展，执行 **Dev Containers: Attach to Running Container...**，选择 `ros2-humble-lab-dev-1`，打开 `/workspaces/ros2_ws`，即可在现有 ROS 环境中编辑、编译和调试。连接使用现有运行容器。[官方远程容器开发说明](https://code.visualstudio.com/remote/advancedcontainers/develop-remote-host)

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

## Web SSH 管理

侧栏 **SSH 管理** 支持生成 ED25519、RSA、ECDSA 密钥，提供连接、密钥、原生 Config、主机指纹、公钥部署、连接诊断及独立 Zellij SSH 终端。首次接入 Config 前可预览差异，密钥和配置操作沿用当前管理员登录状态，删除和配置覆盖提供一次操作确认。localhost、局域网和私有组网支持通过 HTTP 使用全部 SSH 操作。HTTPS 可选。完整使用与部署流程见 [SSH.md](SSH.md)。

管理员密码可使用任意长度和字符组合，也可留空。首次设置、登录和修改密码采用相同规则。已登录管理员修改密码直接保存新密码，其他浏览器的旧登录会失效。


## 知识库

侧栏 **知识库** 可添加主机已有目录，或输入路径新建知识库，路径支持 `~/`。每个知识库直接使用目录中的 `.md` / `.markdown` 文件，并在 SQLite 保存目录关联和名称。

打开知识库后，可按目录浏览、按文件名或路径搜索笔记，阅读渲染后的 Markdown，或切换到编辑模式。支持中文、新建、重命名、删除、下载和 `Ctrl+S` / `⌘S` 保存。新建笔记可填写 `研究/定位.md`，自动创建缺少的父目录。相对 Markdown 链接可打开同库笔记，本地图片通过文件接口显示。

卡片上的“移除”删除目录关联。“删除目录”会确认目标并将整个目录移入父目录的 `.remotehub-trash`。笔记删除使用同一回收机制，可在文件管理器进入所在目录后通过“回收记录”恢复。保存复用文件版本检查，遇到外部修改时保留编辑内容并提示冲突。单篇笔记编辑上限为 1 MiB，目录扫描每次最多 10000 个条目 / 3 秒，达到上限会提示部分结果。

Markdown 使用本地托管的 [Marked](https://marked.js.org/) 与 [DOMPurify](https://github.com/cure53/DOMPurify)。固定版本、来源与许可在 `static/vendor/`，页面运行时从本机加载这些文件。

添加、新建或编辑知识库时，可点击路径旁的“浏览”，使用目录选择器逐层进入文件夹、返回上级、切换文件根目录，并可新建文件夹后选中。知识库目录树用箭头展开多级目录，切换笔记保留展开状态，只显示文件夹及 Markdown 笔记。笔记中的同库目录链接会定位并展开对应目录。Markdown 表格使用完整阅读宽度，单元格自动换行。

桌面侧栏可通过“工作空间”旁的按钮收缩为图标导航，选择会保存在当前浏览器。各模块页面顶部仅显示主标题。SSH 连接的分组和收藏条件统一放入“筛选”浮层，修改后立即生效。

## 远程连接

侧栏进入“远程连接”，或访问 `http://主机地址:8765/#remote`。顶部同时显示 Tailscale 和 RustDesk 状态，下面分别管理组网设备、RustDesk 客户端及设置。沿用控制台的管理员登录、Host / Origin 和 CSRF 检查。

Tailscale 使用本机官方 CLI。实际接入版本为 1.104.7，读取 `status --json` 与 `get --json`，设置使用 `tailscale set` 的指定字段，连接使用保留已有配置的 `tailscale up`。支持设备搜索、在线筛选、组网地址复制、单设备 Ping、原生 `netcheck`，以及 DNS、子网路由、入站拦截和出口节点设置。全网账户与访问策略可通过“组网管理后台”进入官方管理页面。

断开或重连组网前确认一次，断开请求先返回应答再执行 CLI。通过 Tailscale 访问时，这会中断当前入口，页面提供已有局域网入口。操作结果可在局域网入口刷新查看。组网断开时，设备列表等待重新连接后更新。入站拦截和出口路由更改会提示其对当前远程访问的影响。

RustDesk 适配本机 1.5.3 的内部 Unix IPC，源码依据见 [官方 IPC](https://github.com/rustdesk/rustdesk/blob/1.5.3/src/ipc.rs)。消息帧依据 [hbb_common BytesCodec fae47e0](https://github.com/rustdesk/hbb_common/blob/fae47e024dd83cef6aaecde0aa7d11731df11649/src/bytes_codec.rs)。支持原生 ID、在线/接入状态、活动远程控制连接数、网络与权限设置、临时密码查看/复制和固定密码设置/清除。固定密码只在请求及 IPC 内存中传递，由原生客户端保存。设置按目标字段比较并合并，保留其他原生选项。

“从当前设备连接此主机”调用当前设备安装的 RustDesk；“在主机上发起连接”调用服务宿主机的 RustDesk 窗口，支持桌面和文件传输。用户登录后的后台恢复由控制台生命周期中的守护检查负责，复用已运行的客户端，退出后通过原生 `--server` 启动。自动运行状态保存在 `.runtime/remote-connect/rustdesk-autostart.json`。独立 rustdesk-live 的自动运行选择已迁移至这里。

本机原独立 `8788` 管理服务及其“我的应用”入口已迁入本模块。原项目目录保留作为迁移备份。当前服务入口统一使用控制台的 `8765` 端口。

可在 `.env` 通过 `ORH_RUSTDESK_BIN`、`ORH_TAILSCALE_BIN` 指定程序路径。当前服务账户需要有相应 CLI 操作权限。RustDesk 版本更新后需验证内部 IPC 兼容性。原生界面的屏幕、键鼠和 FileVault 权限遵循操作系统流程，完整重启后的恢复以用户登录为起点。
