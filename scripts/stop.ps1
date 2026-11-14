#Requires -Version 5.1
<#
.SYNOPSIS
    Stop the running music2score web server (and any leftover job workers).
#>
[CmdletBinding()]
param(
    [int]$Port = 0
)

$ErrorActionPreference = "SilentlyContinue"

$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$Root = Split-Path -Parent $ScriptDir

if (-not $env:MUSIC2SCORE_HOME) {
    $env:MUSIC2SCORE_HOME = Join-Path $Root "runtime"
}

if ($Port -le 0) {
    if ($env:MUSIC2SCORE_PORT) {
        $Port = [int]$env:MUSIC2SCORE_PORT
    }
    else {
        $Port = 8010
    }
}

$ports = @()
for ($candidate = $Port; $candidate -lt $Port + 20; $candidate++) {
    $ports += $candidate
}

function Get-ListeningProcessIds([int]$LocalPort) {
    $ids = @()
    $connections = Get-NetTCPConnection -LocalPort $LocalPort -State Listen -ErrorAction SilentlyContinue
    foreach ($connection in $connections) {
        if ($connection.OwningProcess) {
            $ids += [int]$connection.OwningProcess
        }
    }
    if ($ids.Count -eq 0) {
        # Fallback for systems without Get-NetTCPConnection.
        $lines = netstat -ano -p TCP | Select-String "LISTENING"
        foreach ($line in $lines) {
            $parts = ($line.ToString().Trim() -split '\s+')
            if ($parts.Count -ge 5 -and $parts[1] -match ":$LocalPort$") {
                $ids += [int]$parts[4]
            }
        }
    }
    return $ids | Sort-Object -Unique
}

$stopped = @()
$killedPids = @{}

foreach ($localPort in $ports) {
    foreach ($ownerPid in Get-ListeningProcessIds $localPort) {
        $process = Get-CimInstance Win32_Process -Filter "ProcessId = $ownerPid" -ErrorAction SilentlyContinue
        if ($process -and $process.CommandLine -match "app\.main:app") {
            Stop-Process -Id $ownerPid -Force -ErrorAction SilentlyContinue
            $killedPids[[int]$ownerPid] = $true
            $stopped += "uvicorn (PID $ownerPid, 端口 $localPort)"
        }
    }
}

# The venv interpreter can be a trampoline that spawns the real server as a
# child; stop any remaining app process that was not the socket owner.
$servers = Get-CimInstance Win32_Process -Filter "Name = 'python.exe'" -ErrorAction SilentlyContinue |
    Where-Object { $_.CommandLine -match "app\.main:app" }
foreach ($server in $servers) {
    $serverPid = [int]$server.ProcessId
    if (-not $killedPids.ContainsKey($serverPid)) {
        Stop-Process -Id $serverPid -Force -ErrorAction SilentlyContinue
        $killedPids[$serverPid] = $true
        $stopped += "server (PID $serverPid)"
    }
}

# A transcription worker may outlive the API process; stop it too so the GPU
# is released when the user closes the app.
$workers = Get-CimInstance Win32_Process -Filter "Name = 'python.exe'" -ErrorAction SilentlyContinue |
    Where-Object { $_.CommandLine -match "app\.worker" }
foreach ($worker in $workers) {
    Stop-Process -Id $worker.ProcessId -Force -ErrorAction SilentlyContinue
    $stopped += "worker (PID $($worker.ProcessId))"
}

$stopped = $stopped | Sort-Object -Unique

Write-Host ""
if ($stopped.Count -gt 0) {
    Write-Host "已停止：" -ForegroundColor Green
    foreach ($item in $stopped) {
        Write-Host "  - $item" -ForegroundColor DarkGray
    }
}
else {
    Write-Host "没有检测到正在运行的音乐扒谱服务。" -ForegroundColor Yellow
}
Write-Host ""
