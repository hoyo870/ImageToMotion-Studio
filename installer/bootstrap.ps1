param([switch]$Fresh,[switch]$VerifyOnly)
$ErrorActionPreference='Stop'
$root=Split-Path $PSScriptRoot -Parent
$state=Join-Path $root '.state'
New-Item -ItemType Directory -Path $state -Force | Out-Null
$env:PYTHONUTF8='1'
$env:PYTHONIOENCODING='utf-8'
function FileHash([string]$Path) {
 $stream=[System.IO.File]::OpenRead($Path)
 $algorithm=[System.Security.Cryptography.SHA256]::Create()
 try { return [BitConverter]::ToString($algorithm.ComputeHash($stream)).Replace('-','').ToLowerInvariant() }
 finally {$stream.Dispose();$algorithm.Dispose()}
}
$python=Join-Path $root 'runtime\bootstrap\python.exe'
try {
 if (!(Test-Path -LiteralPath $python)) {
  $zip=Join-Path $state 'python-3.12.10-embed-amd64.zip'
  $hash='4acbed6dd1c744b0376e3b1cf57ce906f9dc9e95e68824584c8099a63025a3c3'
  if ((Test-Path -LiteralPath $zip) -and ((FileHash $zip) -ne $hash)) {Remove-Item -LiteralPath $zip -Force}
  if (!(Test-Path -LiteralPath $zip)) {
   $cached=Join-Path (Split-Path $root -Parent) 'AI\ComfyUI_3D_1024\downloads\python.zip'
   if ((Test-Path -LiteralPath $cached) -and ((FileHash $cached) -eq $hash)) { Copy-Item -LiteralPath $cached -Destination $zip }
   else { & curl.exe -fL --retry 3 -o "$zip.part" 'https://www.python.org/ftp/python/3.12.10/python-3.12.10-embed-amd64.zip'; if ($LASTEXITCODE) {throw 'Python download failed'}; Move-Item -LiteralPath "$zip.part" -Destination $zip -Force }
  }
  if ((FileHash $zip) -ne $hash) {throw 'Python archive SHA256 mismatch'}
  $destination=Join-Path $root 'runtime\bootstrap'
  New-Item -ItemType Directory -Path $destination -Force | Out-Null
  & tar.exe -xf $zip -C $destination
  if ($LASTEXITCODE) {throw 'Python archive extraction failed'}
 }
 $opts=@()
 if ($Fresh) {$opts+='--fresh'}
 if ($VerifyOnly) {$opts+='--verify-only'}
 & $python -u (Join-Path $PSScriptRoot 'setup.py') @opts
 if ($LASTEXITCODE) {throw "Setup failed (exit $LASTEXITCODE). See .state\setup.log"}
 exit 0
} catch {Write-Host "ERROR: $_" -ForegroundColor Red; exit 1}
