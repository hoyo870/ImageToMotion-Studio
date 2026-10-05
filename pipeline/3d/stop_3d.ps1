$root = $PSScriptRoot
$pidFile = Join-Path $root 'logs\server.pid'
if (Test-Path -LiteralPath $pidFile) {
    $serverProcessId = [int](Get-Content -LiteralPath $pidFile -Raw).Trim()
    $serverProcess = Get-CimInstance Win32_Process -Filter "ProcessId = $serverProcessId"
    if ($serverProcess -and $serverProcess.ExecutablePath -eq "$root\python_embeded\python.exe" -and $serverProcess.CommandLine -like '*main.py*') {
        try { Invoke-RestMethod 'http://127.0.0.1:8189/queue' -Method Post -ContentType 'application/json' -Body '{"clear":true}' | Out-Null; Invoke-RestMethod 'http://127.0.0.1:8189/interrupt' -Method Post -ContentType 'application/json' -Body '{}' | Out-Null } catch {}
        Stop-Process -Id $serverProcessId -Force
    }
}
