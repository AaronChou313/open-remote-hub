# DSH Web 故障恢复

控制台里的“DeepSeek Harness”打不开时，按本文从上到下处理。默认端口：控制台 `8765`、认证网关 `8767`、原生 DSH `9741`。

## 先跑一条命令

```sh
cd /Users/aaron/Projects/open-remote-hub
.venv/bin/python scripts/dsh_doctor.py
```

输出示例：

```
DSH chain:
  enabled         True
  native port     9741 ok
  native pid      24502 (managed=True)
  native cookie   present (port=9741, age=26499s)
  native healthy  ok
  gateway port    8767 ok
```

| 字段 | 含义 | 不正常时 |
| --- | --- | --- |
| `enabled` | `.env` 的 `ORH_DSH_ENABLED=1` | 改 `.env` 后重启控制台 |
| `native port` | 原生 DSH 是否在 9741 监听 | DSH 进程没起来，见“重启 DSH 本身” |
| `pid` / `managed` | 控制台是否认得这个进程 | `managed=False` 只影响“是否复用”的展示，不再影响认证 |
| `native cookie` | `.runtime/dsh-auth.json` 里的原生 Cookie | `missing` 说明从未换过，或文件被删 |
| `native healthy` | 用该 Cookie 请求 9741 是否 200 | 就是面板打不开的直接原因 |
| `gateway port` | 认证网关 8767 是否在监听 | 控制台进程没起来 |

退出码 `0` 表示链路健康，`1` 表示仍不可用。

## 修复顺序

### 1. 非破坏性：重新换取 Cookie

```sh
.venv/bin/python scripts/dsh_doctor.py --fix
```

它用 `.runtime/dsh-auth.json` 里保存的 launch token，走 DSH 官方启动 URL 重新换一次 Cookie。**不会重启 DSH，也不会打断正在跑的模型任务。**

### 2. 重启控制台

```sh
launchctl kickstart -k gui/$(id -u)/local.openremotehub
```

控制台重启会丢掉进程内的临时状态；DSH supervisor 是独立会话，不会跟着退出。会话 Cookie 存在 SQLite，浏览器登录状态保留。

```sh
# 一次做完：先换 Cookie，不行再重启控制台
.venv/bin/python scripts/dsh_doctor.py --fix --restart
```

### 3. 看日志

```sh
tail -50 .runtime/dsh.log        # 原生 DSH 的 stdout（启动 Token 已遮盖）
tail -50 .runtime/launchd.log    # 控制台 stdout/stderr
```

常见判断：

- `plugin tree failed to load` / `credentials-local` → DSH 自身配置或版本问题，与控制台无关。
- `address already in use` → 9741 被别的进程占了，`lsof -nP -iTCP:9741 -sTCP:LISTEN` 看是谁。
- 大量 `WebSocketDisconnect(1006)` 且伴随 `Shutting down` → 控制台重启时的正常噪声，不是故障。

### 4. 最后手段：重启 DSH 本身

会中断该 Web profile 上正在执行的模型任务，先确认可以断。

```sh
# supervisor 收到 SIGTERM 会带着子进程一起退出
kill "$(python3 -c "import json;print(json.load(open('.runtime/dsh-process.json'))['pid'])")"
```

然后打开控制台“DSH 工作台”，点“启动并进入 DSH”。等它重新打印 `dsh web: http://127.0.0.1:9741/?token=...`（在 `.runtime/dsh.log` 里，Token 已遮盖），supervisor 会自动换好 Cookie。

## 为什么会坏（2026-11-14 案例）

现场表现：`/api/dsh/status` 返回 `running:false, managed:false`，网关对已登录管理员返回 `503 DSH 本机认证暂不可用`，点“启动并进入”则 409。

链路是这样的：

1. 控制台用 `(PID, 创建时间, 启动脚本)` 三元组判断“9741 上这个 DSH 是不是我起的”（`app/dsh.py: managed()`）。
2. 创建时间来自 `psutil` 的 `boot_time + ticks`。系统对时、时钟跳变、PID 回收、控制台重启，都会让三元组与 `.runtime/dsh-process.json` 里记录的值漂移。项目里 `test_managed_pid_tolerates_clock_rounding` 就是为这类漂移加的。
3. 旧实现把 `native_cookie()` 也挂在这个判断上。三元组一旦漂移，Cookie 被当成空字符串，网关转发一个未认证请求，上游 401，网关把它翻译成 503，面板就“连不上”。
4. 这时点“启动”也救不回来：`start()` 看到 9741 上有 listener，判定“进程已存在但未就绪”，直接 409。于是没有任何 UI 路径能恢复，只能重启控制台。

修复（本仓库已包含）：

- `native_cookie()` 不再依赖 `managed()`。Cookie 本身才是凭据，身份簿记漂移不应该把它清空；Cookie 真的失效时上游会 401，结果与以前一致。
- 新增 `recover()`：用保存的 launch token 重新换取 Cookie。
- `start()` 在 listener 存在但认证失败时先尝试 `recover()`，成功就直接进入，不再直接 409。

## 预防

- 不要只 `kill` DSH 子进程而留下 supervisor；要停就停 supervisor（它会带走子进程）。
- `8765`/`8767`/`9741` 不要被其他进程占用；`dsh_doctor.py` 会分别报告。
- 桌面版（默认 `65446`）与 Web profile 共用 `~/.dsh` 数据根，但不共享进程。桌面版正常不代表控制台的 DSH 正常。
- 改完 `.env` 必须重启控制台才生效。
