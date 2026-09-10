$out = @()
$paths = @(
    'HKLM:\SOFTWARE\Microsoft\Windows\CurrentVersion\Uninstall\*',
    'HKLM:\SOFTWARE\WOW6432Node\Microsoft\Windows\CurrentVersion\Uninstall\*',
    'HKCU:\SOFTWARE\Microsoft\Windows\CurrentVersion\Uninstall\*'
)
$apps = Get-ItemProperty $paths -ErrorAction SilentlyContinue | Where-Object { $_.DisplayName }
foreach ($app in $apps) {
    $line = "Name: $($app.DisplayName)`r`n  Uninstall: $($app.UninstallString)`r`n  Location: $($app.InstallLocation)`r`n  Key: $($app.PSPath)"
    $out += $line
}
$out | Out-File -FilePath "d:\mydo\installed_apps.txt" -Encoding UTF8
Write-Host "saved to installed_apps.txt"