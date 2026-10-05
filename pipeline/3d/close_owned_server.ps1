param([int]$ServerPid,[string]$PythonPath)
$ErrorActionPreference='Stop'
$process=Get-CimInstance Win32_Process -Filter "ProcessId = $ServerPid"
if ($process -and $process.ExecutablePath -eq $PythonPath -and $process.CommandLine -match 'ComfyUI.+main.py') {
 Stop-Process -Id $ServerPid -Force
}
for ($attempt=0;$attempt -lt 30;$attempt++) {
 $remaining=Get-Process -Id $ServerPid -ErrorAction SilentlyContinue
 if (!$remaining -or $remaining.HasExited) {exit 0}
 Start-Sleep -Milliseconds 250
}
Write-Output 'Owned server still visible after shutdown'
exit 2
