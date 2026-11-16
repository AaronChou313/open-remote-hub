$ErrorActionPreference = "Stop"
Set-Location (Split-Path $PSScriptRoot -Parent)
python -m pip install --disable-pip-version-check -r desktop/requirements.txt
$version = (Get-Content VERSION -Raw).Trim()
Push-Location mesh
go build -trimpath -ldflags "-s -w -X main.version=$version" -o ..\bin\orh-mesh.exe .\cmd\orh-mesh
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
Pop-Location
python mesh\packaging\notices.py
pyinstaller desktop\orh.spec --noconfirm --distpath build\windows --workpath build\pyinstaller
$iscc = "C:\Program Files (x86)\Inno Setup 6\ISCC.exe"
if (-not (Test-Path $iscc)) { throw "Inno Setup 6 not found: $iscc" }
& $iscc windows\orh.iss
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
