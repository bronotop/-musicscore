#Requires -Version 5.1
<#
.SYNOPSIS
    Create desktop / Start Menu shortcuts for the one-click launcher.
#>
[CmdletBinding()]
param(
    [switch]$NoStartMenu
)

$ErrorActionPreference = "Stop"

$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$Root = Split-Path -Parent $ScriptDir
$Target = Join-Path $Root "启动音乐扒谱.bat"
$Icon = Join-Path $Root "assets\music2score.ico"

if (-not (Test-Path $Target)) {
    Write-Host "找不到启动脚本：$Target" -ForegroundColor Red
    exit 1
}

$shell = New-Object -ComObject WScript.Shell
$created = @()

$desktop = [Environment]::GetFolderPath("Desktop")
if ($desktop) {
    $path = Join-Path $desktop "音乐扒谱.lnk"
    $shortcut = $shell.CreateShortcut($path)
    $shortcut.TargetPath = $Target
    $shortcut.WorkingDirectory = $Root
    if (Test-Path $Icon) { $shortcut.IconLocation = "$Icon,0" }
    $shortcut.Description = "一键启动音乐扒谱（本地 Web 应用）"
    $shortcut.WindowStyle = 1
    $shortcut.Save()
    $created += $path
}

if (-not $NoStartMenu) {
    $programs = [Environment]::GetFolderPath("Programs")
    if ($programs) {
        $path = Join-Path $programs "音乐扒谱.lnk"
        $shortcut = $shell.CreateShortcut($path)
        $shortcut.TargetPath = $Target
        $shortcut.WorkingDirectory = $Root
        if (Test-Path $Icon) { $shortcut.IconLocation = "$Icon,0" }
        $shortcut.Description = "一键启动音乐扒谱（本地 Web 应用）"
        $shortcut.WindowStyle = 1
        $shortcut.Save()
        $created += $path
    }
}

Write-Host "已创建快捷方式：" -ForegroundColor Green
foreach ($item in $created) {
    Write-Host "  - $item" -ForegroundColor DarkGray
}
