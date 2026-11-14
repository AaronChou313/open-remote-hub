param([switch]$Uninstall)
$ErrorActionPreference = "Stop"
$Repo = Split-Path $PSScriptRoot -Parent
Set-Location $Repo
$TaskName = "OpenRemoteHub"
$ShortcutDir = Join-Path $env:APPDATA "Microsoft\Windows\Start Menu\Programs"

if ($Uninstall) {
    $Existing = Get-ScheduledTask -TaskName $TaskName -ErrorAction SilentlyContinue
    if ($Existing) { Stop-ScheduledTask -TaskName $TaskName; Unregister-ScheduledTask -TaskName $TaskName -Confirm:$false }
    Remove-Item (Join-Path $ShortcutDir "OpenRemoteHub.lnk") -ErrorAction SilentlyContinue
    Remove-Item (Join-Path $ShortcutDir "OpenRemoteHub 停止.lnk") -ErrorAction SilentlyContinue
    Write-Host "已移除 OpenRemoteHub 计划任务与快捷方式；.runtime 中的数据保留。"
    exit 0
}

$Python = Get-Command python -ErrorAction SilentlyContinue
if (-not $Python) { $Python = Get-Command py -ErrorAction SilentlyContinue }
if (-not $Python) { throw "未找到 Python。请安装 Python 3.11+，安装时勾选 Add python.exe to PATH。" }

if (-not (Test-Path ".venv\Scripts\python.exe")) { & $Python.Source -m venv .venv }
Write-Host "安装 Python 依赖…"
& .venv\Scripts\python.exe -m pip install --quiet --upgrade pip
& .venv\Scripts\python.exe -m pip install --quiet -r requirements.txt

if (-not (Test-Path ".env")) {
    $ips = @()
    try {
        $ips = Get-NetIPAddress -AddressFamily IPv4 -ErrorAction SilentlyContinue |
            Where-Object { $_.IPAddress -ne "127.0.0.1" -and $_.IPAddress -notlike "169.254.*" } |
            Select-Object -ExpandProperty IPAddress
    } catch {}
    $allowed = ($ips -join ",")
    [IO.File]::WriteAllLines((Join-Path $Repo ".env"), @(
        "ORH_HOST=0.0.0.0",
        "ORH_PORT=8765",
        "ORH_ALLOWED_HOSTS=$allowed",
        "ORH_DSH_ENABLED=0"
    ), (New-Object System.Text.UTF8Encoding($false)))
    Write-Host "已生成 .env（允许的主机：$allowed）"
}

if (-not $env:ORH_MESH_SOURCE) {
    $Candidate = Join-Path $Repo "dist\orh-mesh-windows-amd64.exe"
    if (Test-Path $Candidate) { $env:ORH_MESH_SOURCE = (Resolve-Path $Candidate).Path }
}
& .venv\Scripts\python.exe scripts\mesh_setup.py
if (-not (Test-Path "bin\orh-mesh.exe")) {
    throw "缺少组网组件。请把 orh-mesh-windows-amd64.exe 放到 dist\ 或设置 ORH_MESH_SOURCE 后重试。"
}

$Action = New-ScheduledTaskAction -Execute "cmd.exe" -Argument "/c `"$Repo\scripts\server.cmd`"" -WorkingDirectory $Repo
$Trigger = New-ScheduledTaskTrigger -AtLogOn -User $env:USERNAME
$Principal = New-ScheduledTaskPrincipal -UserId "$env:USERDOMAIN\$env:USERNAME" -LogonType Interactive -RunLevel Limited
$Settings = New-ScheduledTaskSettingsSet -RestartCount 3 -RestartInterval (New-TimeSpan -Minutes 1) -ExecutionTimeLimit ([TimeSpan]::Zero) -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries
Register-ScheduledTask -TaskName $TaskName -Action $Action -Trigger $Trigger -Principal $Principal -Settings $Settings -Force | Out-Null

$Shell = New-Object -ComObject WScript.Shell
$Open = $Shell.CreateShortcut((Join-Path $ShortcutDir "OpenRemoteHub.lnk"))
$Open.TargetPath = "http://127.0.0.1:8765/"
$Open.Save()
$Stop = $Shell.CreateShortcut((Join-Path $ShortcutDir "OpenRemoteHub 停止.lnk"))
$Stop.TargetPath = "$Repo\scripts\stop.cmd"
$Stop.WorkingDirectory = $Repo
$Stop.Save()

Start-ScheduledTask -TaskName $TaskName
for ($i = 0; $i -lt 60; $i++) {
    Start-Sleep -Milliseconds 500
    try {
        $response = Invoke-WebRequest -UseBasicParsing -Uri "http://127.0.0.1:8765/" -TimeoutSec 2
        if ($response.StatusCode -eq 200) { break }
    } catch {}
}
Write-Host "OpenRemoteHub 已启动：http://127.0.0.1:8765/"
Write-Host "首次打开设置管理员密码，然后在控制台绑定 Cloud 账号；ORN 会随控制台启动。"
Start-Process "http://127.0.0.1:8765/"
