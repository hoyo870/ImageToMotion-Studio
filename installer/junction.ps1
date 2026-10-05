param([string]$Destination,[string]$Source)
$ErrorActionPreference='Stop'
New-Item -ItemType Junction -Path $Destination -Target $Source | Out-Null
