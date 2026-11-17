# Creates a "Belfort AI" shortcut on your Desktop (logo icon, no console window).
# Run once:  powershell -ExecutionPolicy Bypass -File scripts\create_shortcut.ps1
$root = Split-Path -Parent $PSScriptRoot
$desktop = [Environment]::GetFolderPath("Desktop")
$lnk = (New-Object -ComObject WScript.Shell).CreateShortcut((Join-Path $desktop "Belfort AI.lnk"))
$lnk.TargetPath = Join-Path $root ".venv\Scripts\pythonw.exe"
$lnk.Arguments = "belfort.py"
$lnk.WorkingDirectory = $root
$lnk.IconLocation = Join-Path $PSScriptRoot "belfort.ico"
$lnk.Save()
Write-Output "Shortcut created on your Desktop. Right-click it, Show more options, Pin to taskbar if you like."
