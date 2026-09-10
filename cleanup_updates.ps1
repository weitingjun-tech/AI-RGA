# Requires admin elevation - cleans Windows Update cache
$ErrorActionPreference = 'SilentlyContinue'

# Check admin
$isAdmin = ([Security.Principal.WindowsPrincipal][Security.Principal.WindowsIdentity]::GetCurrent()).IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)
Write-Host ("IsAdmin: " + $isAdmin)
if (-not $isAdmin) { Write-Host "NOT ELEVATED - aborting"; exit 1 }

function Get-FreeGB { return [math]::Round((Get-PSDrive C).Free/1GB, 2) }
$before = Get-FreeGB
Write-Host ("Free before: " + $before + " GB")

Write-Host "Stopping update services..."
Stop-Service wuauserv -Force
Stop-Service bits -Force
Stop-Service dosvc -Force

Write-Host "Cleaning SoftwareDistribution\Download..."
Remove-Item "C:\Windows\SoftwareDistribution\Download\*" -Recurse -Force

Write-Host "Restarting services..."
Start-Service bits
Start-Service wuauserv
Start-Service dosvc

$after = Get-FreeGB
Write-Host ("Free after: " + $after + " GB")
Write-Host ("Space freed: " + [math]::Round($after - $before, 2) + " GB")