param(
    [switch]$SkipSmokeTest
)

$ErrorActionPreference = 'Stop'
Set-Location $PSScriptRoot

$python = Join-Path $PSScriptRoot '.venv\Scripts\python.exe'
if (-not (Test-Path $python)) {
    $python = 'python'
}

& $python -m pip install --upgrade certifi pyinstaller PyMuPDF tkinterdnd2
& $python -m compileall pdf_to_formatted_markdown.py pdf_to_formatted_markdown_gui.py
& $python -m PyInstaller --noconfirm --clean pdf2md-gui.spec

$distDir = Join-Path $PSScriptRoot 'dist'
$configPath = Join-Path $PSScriptRoot 'pdf2md.config'
if (Test-Path $configPath) {
    Copy-Item $configPath (Join-Path $distDir 'pdf2md.config') -Force
}

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

Get-Item $exePath, (Join-Path $distDir 'pdf2md.config') | Select-Object FullName, Length, LastWriteTime