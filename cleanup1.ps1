$ErrorActionPreference = 'SilentlyContinue'

function Get-FreeGB {
    return [math]::Round((Get-PSDrive C).Free/1GB, 2)
}

$before = Get-FreeGB
Write-Host ("Free space before: " + $before + " GB")

# 1. NVIDIA shader cache
Write-Host "`n[1/3] Cleaning NVIDIA shader cache..."
Remove-Item "C:\Users\lizhi3\AppData\Local\NVIDIA\DXCache\*" -Recurse -Force
Remove-Item "C:\Users\lizhi3\AppData\Local\NVIDIA\GLCache\*" -Recurse -Force

# 2. JianyingPro cache (NOT Projects - user drafts)
Write-Host "[2/3] Cleaning JianyingPro cache..."
$jy = "C:\Users\lizhi3\AppData\Local\JianyingPro\User Data"
Remove-Item "$jy\Cache\*" -Recurse -Force
Remove-Item "$jy\Log\*" -Recurse -Force
Remove-Item "$jy\Crash\*" -Recurse -Force
Remove-Item "$jy\Tracking\*" -Recurse -Force

# 3. Temp files
Write-Host "[3/3] Cleaning temp files..."
Remove-Item "C:\Users\lizhi3\.cache\*" -Recurse -Force
Remove-Item "C:\Users\lizhi3\AppData\Local\Temp\*" -Recurse -Force
Remove-Item "C:\Users\lizhi3\AppData\Local\app_shell_cache_6383\*" -Recurse -Force

$after = Get-FreeGB
Write-Host ("`nFree space after: " + $after + " GB")
Write-Host ("Space freed: " + [math]::Round($after - $before, 2) + " GB")