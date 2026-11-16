# DSH Web 故障恢复

控制台、DSH 认证网关与原生 DSH 默认分别使用 `8765`、`8767`、`9741`。

## 在界面恢复

1. 在目标设备的“功能管理”启用 DSH。目标电脑需安装 DeepSeek Harness 桌面版或 `dsh` 命令。
2. 打开“DSH 工作台”。ORH 会尝试接续已有 ORH supervisor 的本机认证，包括从源码版迁移的实例。
3. 显示“需要恢复认证”时，点击“恢复认证并进入”。该操作用官方启动 Token 换取 Cookie，原有模型任务继续运行。
4. 认证恢复失败且实例由 ORH 管理时，可点击“重启 DSH”。确认提示会说明当前模型任务将中断。
5. 如果实例由原生桌面客户端或其他终端启动，先在原客户端退出该实例，再从 ORH 点击“启动并进入 DSH”。

首次进入后，在 DSH 原生界面配置模型账号、工作目录和插件。ORH 使用目标电脑已有的 DSH 配置与会话。

## 安装与自定义路径

ORH 自动检测 macOS 的 `/Applications/DeepSeek Harness.app`、PATH 中的 `dsh` 和已安装的 npm 包。自定义安装可在目标设备 `.env` 设置 `ORH_DSH_BIN`，然后重启 ORH 后台并重新检测。

## 本机排查

安装版的数据位于 macOS `~/Library/Application Support/OpenRemoteHub/.runtime`、Linux `~/.local/share/openremotehub/.runtime`。`dsh.log` 保存原生输出，`dsh-supervisor.log` 保存 supervisor 错误。认证文件 `dsh-auth.json` 包含私有凭据，应保留在本机。

源码运行时，可在仓库执行以下命令。

```sh
.venv/bin/python scripts/dsh_doctor.py
.venv/bin/python scripts/dsh_doctor.py --fix
```

安装版后台与源码版 DSH supervisor 生命周期独立。重启 ORH 后台后，已启动的 DSH 任务会继续运行，认证恢复由工作台完成。
