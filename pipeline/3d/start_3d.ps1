$ErrorActionPreference = 'Stop'
$root = $PSScriptRoot
$env:PYTHONUTF8 = '1'
$env:PYTHONIOENCODING = 'utf-8'
if (Get-NetTCPConnection -LocalPort 8189 -State Listen -ErrorAction SilentlyContinue) { Write-Output 'Port 8189 is already listening.'; exit }
$process = Start-Process -FilePath "$root\python_embeded\python.exe" -ArgumentList @('-u', 'ComfyUI\main.py', '--windows-standalone-build', '--listen', '127.0.0.1', '--port', '8189', '--lowvram', '--disable-dynamic-vram', '--disable-async-offload', '--reserve-vram', '1', '--use-pytorch-cross-attention', '--preview-method', 'none', '--disable-auto-launch') -WorkingDirectory $root -WindowStyle Hidden -RedirectStandardOutput "$root\logs\server.stdout.log" -RedirectStandardError "$root\logs\server.stderr.log" -PassThru
Set-Content -LiteralPath "$root\logs\server.pid" -Value $process.Id
Write-Output "3D ComfyUI PID: $($process.Id), http://127.0.0.1:8189"
