$ErrorActionPreference = 'Stop'
$projectRoot = $PSScriptRoot
$launcher = Join-Path $projectRoot 'run_monitor.vbs'

$startup = [Environment]::GetFolderPath('Startup')
$shortcutPath = Join-Path $startup 'AI Usage Pulse.lnk'
$legacyShortcutPath = Join-Path $startup 'New API Monitor.lnk'
$shell = New-Object -ComObject WScript.Shell
$shortcut = $shell.CreateShortcut($shortcutPath)
$shortcut.TargetPath = $launcher
$shortcut.WorkingDirectory = $projectRoot
$shortcut.Description = 'New API and ChatGPT usage monitor'
$shortcut.Save()

if (Test-Path -LiteralPath $legacyShortcutPath) {
    Remove-Item -LiteralPath $legacyShortcutPath
}
Write-Host "Startup shortcut installed: $shortcutPath"
