# Web SSH 管理中心

在控制台侧栏打开 **SSH 管理**。此模块使用运行 RemoteHub 的系统账户及其 OpenSSH，连接从宿主机发起。

## 使用流程

1. **连接管理** 自动发现 `~/.ssh/config` 和 Include 中的具体 Host 别名。可搜索、按分组筛选、收藏。通配 Host 规则显示在 SSH 配置中。
2. 新连接保存到 `~/.ssh/openremotehub.conf`。首次使用，在 **SSH 配置 → 接入原生 Config** 中查看差异并验证管理员密码。独立 Include 放在最前，遵循 OpenSSH 首值优先规则。原配置保留备份。
3. 点击 **连接**，直接打开原生 Zellij Web 终端。再次点击进入该连接仍在运行的专用会话。**管理 → 新建独立终端** 支持同一连接的多个终端。浏览器关闭会脱离终端，SSH 进程继续运行。
4. SSH 退出后，控制台可创建新的连接会话。查看旧终端只显示其退出状态。系统重启会结束原有计算进程，需要用户主动重新连接。
5. **管理 → 主机指纹** 可查看、扫描、核验、保存或移除指定主机记录。首次扫描的结果未经信任，需通过独立渠道核验后确认。指纹变化阻止自动连接。
6. **密钥管理** 支持生成 ED25519、导入密钥对或公钥、查看指纹、复制或下载公钥、生成缺失公钥、修改口令、私钥导出和删除。私钥相关高风险操作要求管理员复验，删除会检查连接引用。备份可在相应标签页恢复。
7. **管理 → 部署公钥** 选择本地密钥对，在原生终端中输入目标密码或密钥口令。固定脚本仅追加公钥、检查已有记录、设置权限，随后强制公钥认证进行验证。
8. **连接诊断** 检查地址、SSH 握手、主机身份和公钥认证。检查有超时及取消，结果区分网络、连接拒绝、指纹错误、认证失败和交互式认证。

## 配置边界

生效配置由系统 `ssh -G` 求值，包括 Host、Match 和 Include。发现过程仅提取别名及来源，支持引号路径、glob、递归 Include 和重复条目标记。软链接 Include 通过规范目标进行只读核验，目标路径和内容摘要均绑定到授权版本。无法核验的来源会阻止连接并提示修复。相对 Include 由原生 OpenSSH 以用户 `~/.ssh` 为基础解析。复杂的动态 Include 可能无法自动枚举所有别名，其已知别名仍按原生规则求值。

高级编辑面向 SSH 管理目录内已发现的配置，包括子目录文件。保存前预览差异，执行 OpenSSH 语法校验，再以管理员密码确认。管理范围之外及软链接的 Include 可查看，保持只读。原生 config 本身为软链接时，已有连接仍可使用，新增受管 Include 需在外部工具管理的配置源中接入。`openremotehub.conf` 通过连接表单编辑。

`Match exec`、`ProxyCommand`、`LocalCommand`、`KnownHostsCommand` 是可执行配置。自动发现时不会执行这些指令。核验并授权当前配置版本后，才允许原生求值或连接，配置改变后需重新核验。语法验证在私有镜像中将 Match exec 替换为固定的 false 命令。普通连接表单只接受结构化字段。

运行时通过私有 OpenSSH 策略 Include 文件统一约束主机身份检查、SSH 连接复用和本地命令，原生 ProxyJump 的子连接也遵循该策略。用户和系统原始配置按原生顺序读入。默认使用严格主机身份检查。交互式首次连接允许 OpenSSH 展示指纹并由用户确认。使用 ProxyJump 的连接通过 OpenSSH 原生跳板机制连接，自动 keyscan 目前只支持直连。跳板首次认证和指纹核验请在加密原生终端中完成。外部 UserKnownHostsFile 和系统指纹文件继续由 OpenSSH 校验，Web 中的增删限定于管理目录的 known_hosts。

指纹移除支持散列记录和共享主机行，保留其他主机。通配符记录通过增加目标主机的否定匹配保留其他主机。更新或移除已有指纹需要管理员复验。带 authorized_keys 选项的公钥需提供标准的 `类型 base64 备注` 公钥文件。

文件使用权限检查、无软链接路径、进程间锁、原子写入、内容修订检查及私有备份。连接配置跨文件与 SQLite 更新有恢复日志，服务中断后自动核对。密钥创建采用独占发布，已有文件不会被覆盖。软件安装、系统 SSH 服务和真实用户配置均不属于测试环境。

## 私有网络访问与可选 HTTPS

localhost、局域网和私有组网通过 HTTP 即可使用全部 SSH 操作，包括口令输入、密钥导入导出、配置编辑和原生网页终端。默认允许实际连接来源为 127.0.0.0/8、10.0.0.0/8、172.16.0.0/12、192.168.0.0/16、100.64.0.0/10、::1/128、fc00::/7 和 fe80::/10。节点小宝的 100.66.1.x 已包含在默认范围内。

可通过 `.env` 的 `ORH_SSH_HTTP_NETWORKS` 设置逗号分隔的 IP 或 CIDR。现有 `ORH_ALLOWED_HOSTS` 仍控制可访问的目标地址，管理员登录、Host/Origin、CSRF、危险操作确认与密码复验继续生效。HTTP 与 WS 使用相同来源策略，不采信客户端提供的 X-Forwarded-For。

RemoteHub 原生 TLS 可直接用于 macOS launchd 和 Linux systemd，无需依赖转发头信任。将有效证书和私钥路径写入私有 `.env`。

```dotenv
ORH_HOST=0.0.0.0
ORH_PORT=8765
ORH_ALLOWED_HOSTS=hub.example.com,192.168.1.20
ORH_TLS_CERT_FILE=/absolute/path/fullchain.pem
ORH_TLS_KEY_FILE=/absolute/path/privkey.pem
```

证书 SAN 需覆盖实际访问的域名或 IP，私钥仅服务账户可读。证书可由现有 ACME 工具或内网 CA 签发。客户端需信任签发 CA。配置完成后重启 RemoteHub，访问 `https://hub.example.com:8765/`。启用 DSH 时，其独立网关端口也使用同一证书。Zellij 内部服务继续只监听 loopback，由控制台通过 WSS 转发。

启用 TLS 后使用 HTTPS 登录一次。浏览器登录 Cookie 在 HTTPS 下带 Secure 属性，旧 HTTP 登录可能需要重新登录。原生 TLS 不接受代理伪造的 X-Forwarded-Proto。若已有反向代理，推荐其通过 HTTPS 回源，保留 Host/Origin 及配置端口。多域名、443 端口转换需匹配现有 Host/Origin allowlist。

当前 HTTP 入口可直接用于允许的私有网络。HTTPS 是可选部署方式，传输加密与 HTTP 操作权限分别显示和判断。

## 数据与恢复

- `~/.ssh/config` 和 `openremotehub.conf` 是原生配置。默认 `ORH_SSH_DIR` 为 `~/.ssh`，可指定独立目录。
- `.runtime/ssh.sqlite3` 保存连接元数据、终端状态、诊断、配置预览、短时复验授权摘要及备份索引。
- `.runtime/ssh-backups/` 保存 0600 备份。私钥备份保留原来的加密状态，应与原私钥同等保护。
- 私钥、口令不进入普通 API 清单。专用私钥导出是管理员复验后的下载响应。口令经禁用回显的 PTY 输入 ssh-keygen，SSH 登录交互由原生终端完成。口令不会写入 argv、数据库、URL、日志或临时文件。
- 审计只记录操作类型和目标名称，位于 `.runtime/audit.jsonl`。

备份恢复会检查当前文件修订，并在恢复前另存当前版本。恢复受管配置时同时恢复连接元数据。引用检查覆盖受管连接、可求值的外部连接及原生 IdentityFile 规则，包括通配规则和相对路径。命令配置尚未核验时会阻止密钥删除。

## 测试

```sh
.venv/bin/python -m pytest -q
node tests/ssh-ui.mjs
node --check static/ssh.js

# 一次性 Docker SSH 服务，所有端口仅绑定 localhost
# 测试会删除自身创建的容器和 Zellij 会话
# 镜像中密码仅为隔离测试凭据

docker build -t openremotehub/ssh-test:local tests/fixtures/ssh
.venv/bin/python -m pytest tests/test_ssh_live.py -m live -q
```

普通测试仅操作 pytest 临时 SSH 目录。live 测试覆盖未知指纹、真实握手、公钥认证、密钥轮换阻断、核验更新、密码式公钥部署与幂等、加密私钥认证、两个 WebSocket 客户端、浏览器断开、网关重建、并行连接及显式退出。真实 ProxyJump 验证包含跳板错误指纹被拒绝及核验更新后的公钥登录。原生网关测试需已有本机 Zellij Web 网关初始化凭据，仅私下复制其认证到测试目录。
