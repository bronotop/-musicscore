#Requires -Version 5.1
# Backwards-compatible entry point. The real logic lives in scripts/launch.ps1.
$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
& (Join-Path $ScriptDir "scripts\launch.ps1") @args
exit $LASTEXITCODE
