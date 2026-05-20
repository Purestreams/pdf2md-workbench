param(
    [switch]$SkipSmokeTest
)

$ErrorActionPreference = 'Stop'
Set-Location $PSScriptRoot

$python = Join-Path $PSScriptRoot '.venv\Scripts\python.exe'
if (-not (Test-Path $python)) {
    $python = 'python'
}

& $python -m pip install --upgrade certifi pyinstaller PyMuPDF PySide6 qt-material
& $python -m compileall pdf_to_formatted_markdown.py pdf_to_formatted_markdown_gui.py
& $python -m PyInstaller --noconfirm --clean pdf2md-gui.spec

$distDir = Join-Path $PSScriptRoot 'dist'
$exePath = Join-Path $distDir 'pdf2md-gui.exe'
if (-not (Test-Path $exePath)) {
    throw "Build did not produce $exePath"
}

if (-not $SkipSmokeTest) {
    $process = Start-Process -FilePath $exePath -PassThru
    try {
        Wait-Process -Id $process.Id -Timeout 3 -ErrorAction SilentlyContinue
    } catch {
    }
    $process.Refresh()
    if ($process.HasExited) {
        throw "GUI exited quickly with code $($process.ExitCode)"
    }
    Stop-Process -Id $process.Id -Force
}

$runtimeConfigRoot = if ($env:APPDATA) { Join-Path $env:APPDATA 'PDF2MD Workbench' } else { Join-Path (Join-Path $HOME 'AppData\Roaming') 'PDF2MD Workbench' }
Get-Item $exePath | Select-Object FullName, Length, LastWriteTime
Write-Host "Runtime config path: $(Join-Path $runtimeConfigRoot 'pdf2md.config')"