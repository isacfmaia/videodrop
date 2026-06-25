param(
    [switch]$SkipInstaller
)

$ErrorActionPreference = "Stop"

$Root = Split-Path -Parent $PSScriptRoot
$DesktopVenv = Join-Path $Root ".venv-desktop"
$Python = Join-Path $DesktopVenv "Scripts\python.exe"
$IconPath = Join-Path $Root "build\windows\videodrop.ico"
$InstallerScript = Join-Path $Root "installer\videodrop.iss"

if (-not (Test-Path $Python)) {
    python -m venv $DesktopVenv
}

& $Python -m pip install --upgrade pip
& $Python -m pip install -r (Join-Path $Root "requirements-desktop.txt")
& $Python (Join-Path $Root "scripts\make_windows_icon.py")

$PyInstallerArgs = @(
    "--noconfirm",
    "--clean",
    "--windowed",
    "--name", "VideoDrop",
    "--icon", $IconPath,
    "--paths", $Root,
    "--add-data", "$Root\static;static",
    "--collect-all", "yt_dlp",
    "--collect-all", "imageio_ffmpeg",
    "--hidden-import", "uvicorn.loops.auto",
    "--hidden-import", "uvicorn.protocols.http.auto",
    "--hidden-import", "uvicorn.protocols.websockets.auto",
    "--hidden-import", "uvicorn.lifespan.on",
    (Join-Path $Root "desktop_launcher.py")
)

& $Python -m PyInstaller @PyInstallerArgs

if ($SkipInstaller) {
    Write-Host "Build pronto em dist\VideoDrop."
    exit 0
}

$InnoRegistryRoots = @(
    "HKLM:\SOFTWARE\Microsoft\Windows\CurrentVersion\Uninstall\Inno Setup 6_is1",
    "HKLM:\SOFTWARE\WOW6432Node\Microsoft\Windows\CurrentVersion\Uninstall\Inno Setup 6_is1",
    "HKCU:\SOFTWARE\Microsoft\Windows\CurrentVersion\Uninstall\Inno Setup 6_is1"
)

$InnoRegistryPaths = $InnoRegistryRoots |
    ForEach-Object {
        $item = Get-ItemProperty -Path $_ -ErrorAction SilentlyContinue
        if ($item.InstallLocation) { Join-Path $item.InstallLocation "ISCC.exe" }
    }

$InnoCandidates = @(
    (Get-Command "ISCC.exe" -ErrorAction SilentlyContinue).Source,
    (Join-Path ${env:ProgramFiles(x86)} "Inno Setup 6\ISCC.exe"),
    (Join-Path $env:ProgramFiles "Inno Setup 6\ISCC.exe"),
    "D:\Programs\Inno Setup 6\ISCC.exe"
) + @(
    $InnoRegistryPaths
) | Where-Object { $_ -and (Test-Path $_) }

if (-not $InnoCandidates) {
    Write-Host "Build pronto em dist\VideoDrop. Instale o Inno Setup 6 para gerar o instalador."
    exit 0
}

& $InnoCandidates[0] $InstallerScript
Write-Host "Instalador pronto em dist\installer."
