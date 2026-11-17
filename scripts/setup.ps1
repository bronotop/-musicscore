#Requires -Version 5.1
<#
.SYNOPSIS
    首次运行安装脚本：自动创建 Python 环境、安装依赖、下载核心模型。

.DESCRIPTION
    双击 启动音乐扒谱.bat 时，如果没有 .venv，启动器会自动调用本脚本。
    也可以手动运行：
        powershell -ExecutionPolicy Bypass -File scripts\setup.ps1

    做了什么：
      1. 查找 Python 3.12；找不到时尝试用 winget 自动安装；
      2. 在项目根目录创建 .venv；
      3. 安装 requirements.txt；检测到 NVIDIA GPU 时自动安装 CUDA 版 PyTorch；
      4. 用 --no-deps 安装 Basic Pitch；
      5. 下载 Demucs / GAME / Whisper 核心模型（可用 -SkipModels 跳过）；
      6. 前端 dist 已随仓库提供，默认不再需要 Node.js。

.PARAMETER Cuda
    强制安装 CUDA 12.8 版 PyTorch。检测到 NVIDIA GPU 时会自动启用。

.PARAMETER Cpu
    强制使用 CPU 版 PyTorch（不自动安装 CUDA 版）。

.PARAMETER CudaIndexUrl
    覆盖 PyTorch wheel 源。

.PARAMETER SkipFrontend
    跳过前端构建。仓库已包含 frontend/dist 时不需要构建。

.PARAMETER SkipModels
    跳过核心模型下载。

.PARAMETER Python
    指定 Python 3.12 可执行文件路径。

.PARAMETER Check
    只检查 Python 3.12 是否可找到，不安装任何东西。

.PARAMETER ForceDeps
    忽略“依赖已安装”标记，重新检查/安装依赖。
#>
[CmdletBinding()]
param(
    [switch]$Cuda,
    [switch]$Cpu,
    [string]$CudaIndexUrl = "https://download.pytorch.org/whl/cu128",
    [switch]$SkipFrontend,
    [switch]$SkipModels,
    [string]$Python = "",
    [switch]$Check,
    [switch]$ForceDeps
)

# Native tools (pip/winget/npm) often write warnings to stderr. With
# ErrorActionPreference=Stop, Windows PowerShell 5.1 can turn those warnings
# into terminating NativeCommandError. Use Continue and check $LASTEXITCODE
# explicitly for each external command.
$ErrorActionPreference = "Continue"

if ($Cuda -and $Cpu) {
    throw "不能同时使用 -Cuda 和 -Cpu。"
}

function Write-Step([string]$Text) {
    Write-Host ""
    Write-Host "==> $Text" -ForegroundColor Cyan
}

function Find-Python312 {
    param([string]$Explicit = "")

    if ($Explicit) {
        if (Test-Path $Explicit) { return $Explicit }
        throw "指定的 Python 不存在：$Explicit"
    }

    $pyLauncher = Get-Command py -ErrorAction SilentlyContinue
    if ($pyLauncher) {
        # Windows PowerShell 5.1 turns native stderr into a terminating error
        # when ErrorActionPreference is Stop; suppress it for this probe.
        $previousPreference = $ErrorActionPreference
        $ErrorActionPreference = "SilentlyContinue"
        try {
            $path = & $pyLauncher.Source -3.12 -c "import sys; print(sys.executable)" 2>$null
            $pyExit = $LASTEXITCODE
        }
        finally {
            $ErrorActionPreference = $previousPreference
        }
        if ($pyExit -eq 0 -and $path) {
            $candidate = ($path | Select-Object -Last 1).Trim()
            if ($candidate -and (Test-Path $candidate)) { return $candidate }
        }
    }

    $candidates = @()
    $pythonCmd = Get-Command python -ErrorAction SilentlyContinue
    if ($pythonCmd) { $candidates += $pythonCmd.Source }
    if ($env:APPDATA) {
        $uvRoot = Join-Path $env:APPDATA "uv\python"
        if (Test-Path $uvRoot) {
            foreach ($uvDir in Get-ChildItem $uvRoot -Directory -Filter "cpython-3.12*") {
                $candidates += (Join-Path $uvDir.FullName "python.exe")
            }
        }
    }
    if ($env:LOCALAPPDATA) {
        $candidates += (Join-Path $env:LOCALAPPDATA "Programs\Python\Python312\python.exe")
    }
    $candidates += "C:\Python312\python.exe"
    $candidates += "C:\Program Files\Python312\python.exe"

    foreach ($candidate in $candidates) {
        if ($candidate -and (Test-Path $candidate)) {
            $version = & $candidate -c "import sys; print(str(sys.version_info[0]) + '.' + str(sys.version_info[1]))" 2>$null
            if ($version -eq "3.12") { return $candidate }
        }
    }
    return $null
}

$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$Root = Split-Path -Parent $ScriptDir
Set-Location $Root

if ($Check) {
    $found = Find-Python312 -Explicit $Python
    if ($found) {
        Write-Host "Python 3.12: $found"
        exit 0
    }
    Write-Host "Python 3.12 not found. setup.ps1 will try winget." -ForegroundColor Yellow
    exit 1
}

$Venv = Join-Path $Root ".venv"
$VenvPython = Join-Path $Venv "Scripts\python.exe"

function Test-Dependencies {
    if (-not (Test-Path $VenvPython)) { return $false }
    $previous = $ErrorActionPreference
    $ErrorActionPreference = "SilentlyContinue"
    try {
        & $VenvPython -c "import torch, basic_pitch, audio_separator, librosa, music21, fastapi, uvicorn" 2>$null
        return ($LASTEXITCODE -eq 0)
    }
    finally {
        $ErrorActionPreference = $previous
    }
}

if (-not (Test-Path $VenvPython)) {
    $PythonExe = Find-Python312 -Explicit $Python
    if (-not $PythonExe) {
        $winget = Get-Command winget -ErrorAction SilentlyContinue
        if (-not $winget) {
            throw @"
未找到 Python 3.12，也没有找到 winget。

请先安装 Python 3.12：
  https://www.python.org/downloads/
安装时勾选 "Add Python to PATH"，然后重新双击启动。

或手动运行：
  powershell -ExecutionPolicy Bypass -File scripts\setup.ps1 -Python "<python.exe 路径>"
"@
        }

        Write-Step "未找到 Python 3.12，正在通过 winget 自动安装"
        & $winget.Source install --id Python.Python.3.12 -e --silent `
            --accept-package-agreements --accept-source-agreements
        if ($LASTEXITCODE -ne 0) {
            throw "winget 安装 Python 3.12 失败（退出码 $LASTEXITCODE）。请手动安装后重试。"
        }
        $PythonExe = Find-Python312
        if (-not $PythonExe) {
            throw @"
Python 3.12 已通过 winget 安装，但当前窗口还找不到它。

请重启电脑（或关闭所有命令行窗口）后重新双击启动；
也可以手动运行 setup.ps1 -Python "<python.exe 路径>"。
"@
        }
    }

    Write-Step "创建 Python 虚拟环境 .venv"
    & $PythonExe -m venv $Venv
    if (-not (Test-Path $VenvPython)) {
        throw "创建 .venv 失败。请确认 Python 3.12 安装完整。"
    }
}

$RequirementsPath = Join-Path $Root "requirements.txt"
$RequirementsHash = (Get-FileHash $RequirementsPath -Algorithm SHA256).Hash.ToLower()
$MarkerPath = Join-Path $Venv ".music2score-deps.json"
$DepsReady = $false

if (-not $Cpu -and -not $Cuda) {
    $nvidiaSmi = Get-Command nvidia-smi -ErrorAction SilentlyContinue
    if ($nvidiaSmi) {
        Write-Step "检测到 NVIDIA GPU，默认安装 CUDA 12.8 版 PyTorch（可用 -Cpu 跳过）"
        $Cuda = $true
    }
}

if ((Test-Path $MarkerPath) -and -not $ForceDeps) {
    try {
        $marker = Get-Content $MarkerPath -Raw | ConvertFrom-Json
        $sameRequirements = $marker.requirements_sha256 -eq $RequirementsHash
        $samePitch = $marker.basic_pitch -eq "0.4.0"
        $sameCuda = [bool]$marker.cuda -eq [bool]$Cuda
        if ($sameRequirements -and $samePitch -and $sameCuda) {
            Write-Step "检测到已安装依赖，验证关键模块"
            if (Test-Dependencies) {
                $DepsReady = $true
            }
            else {
                Write-Warning "依赖验证失败，将重新检查/安装。"
            }
        }
        else {
            Write-Step "requirements.txt 或 CUDA 选项已变化，重新检查依赖"
        }
    }
    catch {
        Write-Warning "依赖标记损坏，将重新检查/安装。"
    }
}

if ($DepsReady) {
    Write-Step "依赖已安装且匹配 requirements.txt，跳过 pip 安装"
}
else {
    Write-Step "升级 pip"
    & $VenvPython -m pip install --upgrade pip wheel
    if ($LASTEXITCODE -ne 0) { throw "pip 升级失败。" }

    if ($Cuda) {
        Write-Step "安装 CUDA 版 PyTorch（$CudaIndexUrl）"
        & $VenvPython -m pip install torch torchvision torchaudio --index-url $CudaIndexUrl
        if ($LASTEXITCODE -ne 0) {
            Write-Warning "CUDA 版 PyTorch 安装失败，回退到默认 PyPI 版本（CPU 或系统默认）。"
            & $VenvPython -m pip install torch torchvision torchaudio
            if ($LASTEXITCODE -ne 0) { throw "PyTorch 安装失败。" }
        }
    }

    Write-Step "检查/安装 requirements.txt（已安装的包会跳过）"
    & $VenvPython -m pip install -r $RequirementsPath
    if ($LASTEXITCODE -ne 0) { throw "依赖安装失败。" }

    Write-Step "检查/安装 Basic Pitch（不安装 TensorFlow）"
    & $VenvPython -m pip install --no-deps "basic-pitch==0.4.0"
    if ($LASTEXITCODE -ne 0) { throw "Basic Pitch 安装失败。" }

    Write-Step "验证关键依赖"
    & $VenvPython -c "import torch, basic_pitch, audio_separator, librosa, music21, fastapi, uvicorn; print('torch', torch.__version__, 'cuda', torch.cuda.is_available())"
    if ($LASTEXITCODE -ne 0) { throw "依赖导入失败，请查看上方 pip 输出。" }

    $markerPayload = [ordered]@{
        requirements_sha256 = $RequirementsHash
        basic_pitch = "0.4.0"
        cuda = [bool]$Cuda
        python = "3.12"
        created_at = (Get-Date).ToUniversalTime().ToString("o")
    }
    [System.IO.File]::WriteAllText(
        $MarkerPath,
        ($markerPayload | ConvertTo-Json),
        (New-Object System.Text.UTF8Encoding($false))
    )
    Write-Step "依赖安装完成，已写入安装标记"
}

$DistIndex = Join-Path $Root "frontend\dist\index.html"
if (-not $SkipFrontend) {
    if (Test-Path $DistIndex) {
        Write-Step "前端已包含在仓库中，跳过构建"
    }
    else {
        Write-Step "构建前端"
        $npm = Get-Command npm.cmd -ErrorAction SilentlyContinue
        if (-not $npm) { $npm = Get-Command npm -ErrorAction SilentlyContinue }
        if (-not $npm) {
            Write-Warning "未找到 npm，无法构建前端。请安装 Node.js 18+ 后运行：cd frontend; npm install; npm run build"
        }
        else {
            Push-Location (Join-Path $Root "frontend")
            try {
                if (Test-Path "package-lock.json") {
                    & $npm.Source ci
                }
                else {
                    & $npm.Source install
                }
                if ($LASTEXITCODE -ne 0) { throw "npm install 失败。" }
                & $npm.Source run build
                if ($LASTEXITCODE -ne 0) { throw "npm run build 失败。" }
            }
            finally {
                Pop-Location
            }
        }
    }
}

if (-not $SkipModels) {
    $env:PYTHONPATH = Join-Path $Root "backend"
    if (-not $env:MUSIC2SCORE_HOME) {
        $env:MUSIC2SCORE_HOME = Join-Path $Root "runtime"
    }

    Write-Step "下载核心模型（Demucs / GAME / Whisper small）"
    $downloads = @(
        @{ Label = "GAME 人声模型"; Script = "download_game.py"; Args = @("--size", "medium") },
        @{ Label = "Whisper 歌词模型"; Script = "download_whisper.py"; Args = @("--size", "small") },
        @{ Label = "Demucs 分轨模型"; Script = "download_demucs.py"; Args = @() }
    )
    foreach ($item in $downloads) {
        $scriptPath = Join-Path $Root ("scripts\" + $item.Script)
        if (-not (Test-Path $scriptPath)) {
            Write-Warning "跳过 $($item.Label)：找不到 $scriptPath"
            continue
        }
        Write-Host "  - $($item.Label)"
        try {
            & $VenvPython $scriptPath @($item.Args)
            if ($LASTEXITCODE -ne 0) {
                Write-Warning "  $($item.Label) 下载失败（退出码 $LASTEXITCODE），应用仍可运行，稍后可重试。"
            }
        }
        catch {
            Write-Warning "  $($item.Label) 下载失败：$($_.Exception.Message)"
        }
    }
}

Write-Step "环境检查"
$env:PYTHONPATH = Join-Path $Root "backend"
& $VenvPython -m app.cli doctor

Write-Host ""
Write-Host "安装完成。" -ForegroundColor Green
Write-Host "现在双击 启动音乐扒谱.bat 即可使用。" -ForegroundColor Green
Write-Host "可选：双击 下载MuScriptor模型.bat 添加额外乐器（约 1.2 GB，NC 非商用）。" -ForegroundColor Green
