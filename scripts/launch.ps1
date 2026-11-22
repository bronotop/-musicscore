#Requires -Version 5.1
<#
.SYNOPSIS
    One-click launcher for the music2score local web app.

.DESCRIPTION
    Verifies the Python environment and the built frontend, reuses an already
    running instance when possible, starts uvicorn in this console and opens
    the browser once /api/health answers. Closing the window stops the server.

.PARAMETER NoBrowser
    Start the server without opening a browser (useful for debugging).

.PARAMETER Rebuild
    Force a fresh `npm run build` before starting.

.PARAMETER Port
    Preferred port. Defaults to MUSIC2SCORE_PORT or 8010; the next free port
    is used when the preferred one is taken by another program.
#>
[CmdletBinding()]
param(
    [switch]$NoBrowser,
    [switch]$Rebuild,
    [int]$Port = 0
)

$ErrorActionPreference = "Stop"

function Write-Info([string]$Text) {
    Write-Host $Text -ForegroundColor Cyan
}

function Fail([string]$Text) {
    Write-Host ""
    Write-Host $Text -ForegroundColor Red
    exit 1
}

$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$Root = Split-Path -Parent $ScriptDir
Set-Location $Root

# Optional local-only overrides (gitignored). Set MUSIC2SCORE_PYTHON and/or
# MUSIC2SCORE_HOME here to reuse an existing venv/model directory.
$LocalConfig = Join-Path $Root "launch.local.ps1"
if (Test-Path $LocalConfig) {
    . $LocalConfig
}

if (-not $env:MUSIC2SCORE_HOME) {
    $env:MUSIC2SCORE_HOME = Join-Path $Root "runtime"
}
$HomeDir = $env:MUSIC2SCORE_HOME

if ($env:MUSIC2SCORE_PYTHON) {
    $Python = $env:MUSIC2SCORE_PYTHON
}
else {
    $Python = Join-Path $Root ".venv\Scripts\python.exe"
}

$UsingExternalPython = [bool]$env:MUSIC2SCORE_PYTHON
$NeedsSetup = $false

if (-not (Test-Path $Python)) {
    if ($UsingExternalPython) {
        Fail "MUSIC2SCORE_PYTHON 指向的解释器不存在：$Python"
    }
    $NeedsSetup = $true
}
elseif (-not $UsingExternalPython) {
    $MarkerPath = Join-Path $Root ".venv\.music2score-deps.json"
    $RequirementsPath = Join-Path $Root "requirements.txt"
    if (-not (Test-Path $MarkerPath)) {
        $NeedsSetup = $true
    }
    else {
        try {
            $marker = Get-Content $MarkerPath -Raw | ConvertFrom-Json
            $requirementsHash = (Get-FileHash $RequirementsPath -Algorithm SHA256).Hash.ToLower()
            if ($marker.requirements_sha256 -ne $requirementsHash -or $marker.basic_pitch -ne "0.4.0") {
                $NeedsSetup = $true
            }
        }
        catch {
            $NeedsSetup = $true
        }
    }

    if (-not $NeedsSetup) {
        $SitePackages = Join-Path $Root ".venv\Lib\site-packages"
        foreach ($package in @("torch", "basic_pitch", "audio_separator", "librosa", "music21", "fastapi", "uvicorn")) {
            if (-not (Test-Path (Join-Path $SitePackages $package))) {
                $NeedsSetup = $true
                break
            }
        }
    }
}

if ($NeedsSetup) {
    Write-Host ""
    Write-Info "正在检查/安装运行环境（首次约 5 GB，可能需要 10-30 分钟）。"
    Write-Info "已安装的依赖会跳过，不会重复下载。请保持窗口打开。"
    $Setup = Join-Path $ScriptDir "setup.ps1"
    if (-not (Test-Path $Setup)) {
        Fail "找不到安装脚本：$Setup"
    }
    try {
        & $Setup -SkipFrontend
    }
    catch {
        Fail @"
自动安装失败：$($_.Exception.Message)

请查看上方输出。也可以手动运行：
    powershell -ExecutionPolicy Bypass -File scripts\setup.ps1

或安装 Python 3.12 后重新双击启动。
"@
    }
    if (-not (Test-Path $Python)) {
        Fail "安装脚本执行完毕，但仍找不到 Python：$Python"
    }
}

$env:PYTHONPATH = Join-Path $Root "backend"
$env:PYTHONUTF8 = "1"
$env:PYTHONIOENCODING = "utf-8"

$ModelDir = Join-Path $env:MUSIC2SCORE_HOME "models"
if (-not (Test-Path (Join-Path $ModelDir "htdemucs_ft.yaml"))) {
    Write-Info "提示：未找到核心分轨模型 $ModelDir\htdemucs_ft.yaml"
    Write-Info "请把模型包里的 models 文件夹拖到 $env:MUSIC2SCORE_HOME\ 下，或双击 下载核心模型.bat。"
}
elseif (-not (Test-Path (Join-Path $ModelDir "muscriptor"))) {
    Write-Info "提示：未找到可选模型 MuScriptor（质量档的额外乐器）。"
    Write-Info "需要时双击 下载MuScriptor模型.bat；快速档和基础分轨不受影响。"
}

# ---------------------------------------------------------------- frontend --
$DistIndex = Join-Path $Root "frontend\dist\index.html"
if ($Rebuild -or -not (Test-Path $DistIndex)) {
    Write-Info "首次启动：正在构建前端界面（只需一次，约 10-30 秒）…"
    $npm = Get-Command npm.cmd -ErrorAction SilentlyContinue
    if (-not $npm) {
        $npm = Get-Command npm -ErrorAction SilentlyContinue
    }
    if (-not $npm) {
        Fail @"
找不到 npm，无法构建前端界面。

请安装 Node.js 18+ 后在 frontend 目录执行：
    npm install
    npm run build
"@
    }

    Push-Location (Join-Path $Root "frontend")
    try {
        if (-not (Test-Path "node_modules") -or $Rebuild) {
            Write-Info "安装前端依赖…"
            & $npm.Source install
            if ($LASTEXITCODE -ne 0) { throw "npm install 失败（退出码 $LASTEXITCODE）" }
        }
        Write-Info "编译前端…"
        & $npm.Source run build
        if ($LASTEXITCODE -ne 0) { throw "npm run build 失败（退出码 $LASTEXITCODE）" }
    }
    catch {
        Pop-Location
        Fail "前端构建失败：$($_.Exception.Message)"
    }
    Pop-Location
}

# -------------------------------------------------------------- port probe --
if ($Port -le 0) {
    if ($env:MUSIC2SCORE_PORT) {
        $Port = [int]$env:MUSIC2SCORE_PORT
    }
    else {
        $Port = 8010
    }
}

function Test-AppHealth([int]$Candidate) {
    try {
        $response = Invoke-RestMethod -Uri "http://127.0.0.1:$Candidate/api/health" `
            -TimeoutSec 1 -ErrorAction Stop
        return ($response.service -eq "music2score")
    }
    catch {
        return $false
    }
}

function Test-PortOpen([int]$Candidate) {
    $client = New-Object System.Net.Sockets.TcpClient
    try {
        $async = $client.BeginConnect("127.0.0.1", $Candidate, $null, $null)
        if (-not $async.AsyncWaitHandle.WaitOne(300)) {
            return $false
        }
        $client.EndConnect($async)
        return $true
    }
    catch {
        return $false
    }
    finally {
        $client.Close()
    }
}

$Chosen = 0
for ($candidate = $Port; $candidate -lt $Port + 20; $candidate++) {
    if (Test-AppHealth $candidate) {
        $url = "http://127.0.0.1:$candidate"
        Write-Host ""
        Write-Host "音乐扒谱已经在运行：$url" -ForegroundColor Green
        if (-not $NoBrowser) {
            Start-Process $url
        }
        Start-Sleep -Milliseconds 800
        exit 0
    }
    if (-not (Test-PortOpen $candidate)) {
        $Chosen = $candidate
        break
    }
}

if ($Chosen -eq 0) {
    Fail "端口 $Port-$($Port + 19) 都被占用，无法启动服务。"
}

$BaseUrl = "http://127.0.0.1:$Chosen"

# ------------------------------------------------------------ open browser --
if (-not $NoBrowser) {
    Start-Job -ScriptBlock {
        param([string]$Url, [int]$TimeoutSeconds)
        $deadline = (Get-Date).AddSeconds($TimeoutSeconds)
        while ((Get-Date) -lt $deadline) {
            try {
                $health = Invoke-RestMethod -Uri "$Url/api/health" -TimeoutSec 1 -ErrorAction Stop
                if ($health.service -eq "music2score") {
                    Start-Process $Url
                    return
                }
            }
            catch {
                # Server is still starting up.
            }
            Start-Sleep -Milliseconds 400
        }
    } -ArgumentList $BaseUrl, 240 | Out-Null
}

# ------------------------------------------------------------------- start --
try {
    $Host.UI.RawUI.WindowTitle = "音乐扒谱 music2score - 关闭此窗口即停止服务"
}
catch {
    # Window title is cosmetic.
}

Write-Host ""
Write-Host "  ==============================================" -ForegroundColor DarkCyan
Write-Host "        音乐扒谱 music2score" -ForegroundColor White
Write-Host "  ==============================================" -ForegroundColor DarkCyan
Write-Host "        服务地址：$BaseUrl" -ForegroundColor Green
Write-Host "        关闭此窗口即停止服务" -ForegroundColor DarkGray
Write-Host "  ==============================================" -ForegroundColor DarkCyan
Write-Host ""

& $Python -m uvicorn app.main:app --host 127.0.0.1 --port $Chosen
$exitCode = $LASTEXITCODE

Write-Host ""
if ($exitCode -eq 0) {
    Write-Host "服务已停止。" -ForegroundColor Yellow
}
else {
    Write-Host "服务异常退出（退出码 $exitCode），请查看上方日志。" -ForegroundColor Red
}
exit $exitCode
