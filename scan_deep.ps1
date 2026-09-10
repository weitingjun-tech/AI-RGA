Write-Host "=== JianyingPro\User Data structure ==="
Get-ChildItem "C:\Users\lizhi3\AppData\Local\JianyingPro\User Data" -Force -ErrorAction SilentlyContinue | ForEach-Object {
    $sz = (Get-ChildItem $_.FullName -Recurse -Force -File -ErrorAction SilentlyContinue | Measure-Object -Property Length -Sum).Sum
    Write-Host ("  {0,-40} {1,8} MB" -f $_.Name, [math]::Round($sz/1MB,0))
}

Write-Host "`n=== All installed programs (DisplayName + size) ==="
$paths = @(
    'HKLM:\SOFTWARE\Microsoft\Windows\CurrentVersion\Uninstall\*',
    'HKLM:\SOFTWARE\WOW6432Node\Microsoft\Windows\CurrentVersion\Uninstall\*',
    'HKCU:\SOFTWARE\Microsoft\Windows\CurrentVersion\Uninstall\*'
)
Get-ItemProperty $paths -ErrorAction SilentlyContinue | Where-Object { $_.DisplayName } | Sort-Object DisplayName | ForEach-Object {
    $est = if ($_.EstimatedSize) { [math]::Round($_.EstimatedSize/1024, 0) } else { 0 }
    Write-Host ("  {0,-50} {1,6} MB" -f $_.DisplayName, $est)
}