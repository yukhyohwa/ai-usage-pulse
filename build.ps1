$ErrorActionPreference = 'Stop'
Set-Location $PSScriptRoot

$pyinstaller = Join-Path $PSScriptRoot '.venv\Scripts\pyinstaller.exe'
if (-not (Test-Path -LiteralPath $pyinstaller)) {
    throw 'PyInstaller is not installed. Run: .\.venv\Scripts\python.exe -m pip install -r requirements-dev.txt'
}

& $pyinstaller --noconfirm --clean --onefile --windowed --name UsagePulse main.py
Write-Host "Built: $PSScriptRoot\dist\UsagePulse.exe"
