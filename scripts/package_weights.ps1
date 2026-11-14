#Requires -Version 5.1
<#
.SYNOPSIS
    Package locally downloaded model weights for a GitHub Release.

.DESCRIPTION
    Reads weights from $MUSIC2SCORE_HOME/models (default:
    <repo>/runtime/models), writes one zip per model group plus a SHA-256
    manifest into <repo>/release-assets. Nothing is uploaded automatically.

    Weights are non-commercial where noted. Keep NOTICE, LICENSE and
    THIRD_PARTY_NOTICES.md next to the release assets.

.PARAMETER Source
    Models directory. Defaults to $MUSIC2SCORE_HOME/models or runtime/models.

.PARAMETER OutDir
    Output directory. Defaults to <repo>/release-assets.

.PARAMETER Tag
    Suggested GitHub Release tag, used in the printed command.
#>
[CmdletBinding()]
param(
    [string]$Source = "",
    [string]$OutDir = "",
    [string]$Tag = "v0.1.0-weights"
)

$ErrorActionPreference = "Stop"

$Root = Split-Path -Parent (Split-Path -Parent $MyInvocation.MyCommand.Path)
if (-not $Source) {
    $home = if ($env:MUSIC2SCORE_HOME) { $env:MUSIC2SCORE_HOME } else { Join-Path $Root "runtime" }
    $Source = Join-Path $home "models"
}
if (-not $OutDir) {
    $OutDir = Join-Path $Root "release-assets"
}

if (-not (Test-Path $Source)) {
    throw "Models directory not found: $Source. Download weights first (docs/MODEL_DOWNLOADS.md)."
}
New-Item -ItemType Directory -Force -Path $OutDir | Out-Null

# Use Windows' bundled bsdtar explicitly. Git for Windows also ships a GNU tar
# as tar.exe, which treats "C:\..." as a remote host and fails.
$tarPath = Join-Path $env:SystemRoot "System32\tar.exe"
$tar = if (Test-Path $tarPath) { $tarPath } else { $null }
$manifest = New-Object System.Collections.Generic.List[object]

function Add-Archive {
    param(
        [string]$Name,
        [string[]]$RelativePaths
    )

    $existing = @()
    foreach ($relative in $RelativePaths) {
        $full = Join-Path $Source $relative
        if (Test-Path $full) {
            $existing += $relative
        }
        else {
            Write-Warning "skip missing: $relative"
        }
    }
    if ($existing.Count -eq 0) {
        Write-Warning "no files for $Name; skipped"
        return
    }

    $zip = Join-Path $OutDir "$Name.zip"
    if (Test-Path $zip) { Remove-Item $zip -Force }

    Write-Host "==> $Name.zip" -ForegroundColor Cyan
    if ($tar) {
        & $tar -a -c -f $zip -C $Source @existing
        if ($LASTEXITCODE -ne 0) { throw "tar failed while creating $zip" }
    }
    else {
        $stage = Join-Path $OutDir ".stage-$Name"
        if (Test-Path $stage) { Remove-Item $stage -Recurse -Force }
        New-Item -ItemType Directory -Force -Path $stage | Out-Null
        foreach ($relative in $existing) {
            $destination = Join-Path $stage $relative
            $parent = Split-Path -Parent $destination
            if ($parent) { New-Item -ItemType Directory -Force -Path $parent | Out-Null }
            Copy-Item (Join-Path $Source $relative) -Destination $destination -Recurse -Force
        }
        Compress-Archive -Path (Join-Path $stage "*") -DestinationPath $zip -CompressionLevel Optimal
        Remove-Item $stage -Recurse -Force
    }

    $file = Get-Item $zip
    if ($file.Length -gt 2GB) {
        Write-Warning "$Name.zip is larger than 2 GB; GitHub Release may reject it. Split it or use Git LFS."
    }
    $hash = (Get-FileHash $zip -Algorithm SHA256).Hash
    $manifest.Add([pscustomobject]@{
        name = "$Name.zip"
        bytes = $file.Length
        sha256 = $hash
        contents = $existing
    }) | Out-Null
}

# --- Demucs: .th checkpoints + model YAML files in the models root ----------
$demucsFiles = @()
$demucsFiles += Get-ChildItem $Source -File -Filter "*.yaml" | ForEach-Object { $_.Name }
$demucsFiles += Get-ChildItem $Source -File -Filter "*.th" | ForEach-Object { $_.Name }
Add-Archive -Name "demucs" -RelativePaths $demucsFiles

# --- MuScriptor ------------------------------------------------------------
if (Test-Path (Join-Path $Source "muscriptor")) {
    Add-Archive -Name "muscriptor" -RelativePaths @("muscriptor")
}

# --- GAME ------------------------------------------------------------------
if (Test-Path (Join-Path $Source "game")) {
    Add-Archive -Name "game" -RelativePaths @("game")
}

# --- faster-whisper: one zip per installed size ----------------------------
$whisperRoot = Join-Path $Source "faster-whisper"
if (Test-Path $whisperRoot) {
    Get-ChildItem $whisperRoot -Directory | ForEach-Object {
        Add-Archive -Name "faster-whisper-$($_.Name)" -RelativePaths @("faster-whisper/$($_.Name)")
    }
}

# --- Release metadata ------------------------------------------------------
$utf8NoBom = New-Object System.Text.UTF8Encoding($false)
$manifestPath = Join-Path $OutDir "manifest.json"
$manifestJson = $manifest | ConvertTo-Json -Depth 5
[System.IO.File]::WriteAllText($manifestPath, $manifestJson, $utf8NoBom)
Copy-Item (Join-Path $Root "LICENSE") $OutDir -Force
Copy-Item (Join-Path $Root "NOTICE") $OutDir -Force
Copy-Item (Join-Path $Root "THIRD_PARTY_NOTICES.md") $OutDir -Force

$notes = @"
music2score model weights ($Tag)

**NC = Non-Commercial (non-commercial use only).**
- MuScriptor weights: CC BY-NC 4.0
- ADTOF weights: CC BY-NC-SA 4.0 (installed with the ADTOF pip package; not in these zips)
- Demucs checkpoints: subject to the upstream Meta terms (research use)

See manifest.json for sizes and SHA-256, and THIRD_PARTY_NOTICES.md for the
full attribution. Do not use these weights for commercial products/services.
"@
$notesPath = Join-Path $OutDir "release-notes.md"
[System.IO.File]::WriteAllText($notesPath, $notes, $utf8NoBom)

Write-Host ""
Write-Host "Created:" -ForegroundColor Green
Get-ChildItem $OutDir -File | Sort-Object Name | ForEach-Object {
    Write-Host ("  {0,-32} {1,12:N0} bytes" -f $_.Name, $_.Length)
}
Write-Host ""
Write-Host "Upload with GitHub CLI:" -ForegroundColor Green
Write-Host "  gh release create $Tag `"$OutDir\*`" --title `"music2score model weights $Tag`" --notes-file `"$notesPath`""
Write-Host ""
Write-Host "ADTOF weights are installed inside the adtof-pytorch package; they are not in release-assets." -ForegroundColor Yellow
