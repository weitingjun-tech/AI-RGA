# C盘清理PowerShell脚本 - 需要以管理员身份运行
$ErrorActionPreference = 'SilentlyContinue'

# 检查管理员权限
$isAdmin = ([Security.Principal.WindowsPrincipal][Security.Principal.WindowsIdentity]::GetCurrent()).IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)
if (-not $isAdmin) {
    Write-Host "请以管理员身份运行此脚本" -ForegroundColor Red
    exit 1
}

Write-Host "========================================" -ForegroundColor Cyan
Write-Host "       C盘清理工具 v1.0 (PowerShell版)" -ForegroundColor Cyan
Write-Host "========================================" -ForegroundColor Cyan
Write-Host ""

# 获取开始前的空闲空间
function Get-FreeGB {
    return [math]::Round((Get-PSDrive C).Free/1GB, 2)
}

$before = Get-FreeGB
Write-Host "开始前空闲空间: $before GB"
Write-Host "开始时间: $(Get-Date)"
Write-Host ""

# 1. NVIDIA着色器缓存 (18GB)
Write-Host "[1/7] 清理NVIDIA着色器缓存 (18GB)" -ForegroundColor Yellow
$nvidiaPaths = @(
    "C:\Users\lizhi3\AppData\Local\NVIDIA\DXCache",
    "C:\Users\lizhi3\AppData\Local\NVIDIA\GLCache"
)
foreach ($path in $nvidiaPaths) {
    if (Test-Path $path) {
        Remove-Item $path -Recurse -Force -ErrorAction SilentlyContinue
        Write-Host "   ✓ 已清理: $((Split-Path $path -Leaf))" -ForegroundColor Green
    }
}

# 2. 剪映缓存 (2.1GB)
Write-Host "`n[2/7] 清理剪映缓存 (2.1GB)" -ForegroundColor Yellow
$jianyingPaths = @(
    "C:\Users\lizhi3\AppData\Local\JianyingPro\User Data\Cache",
    "C:\Users\lizhi3\AppData\Local\JianyingPro\User Data\Log",
    "C:\Users\lizhi3\AppData\Local\JianyingPro\User Data\Crash",
    "C:\Users\lizhi3\AppData\Local\JianyingPro\User Data\Tracking"
)
foreach ($path in $jianyingPaths) {
    if (Test-Path $path) {
        Remove-Item $path -Recurse -Force -ErrorAction SilentlyContinue
        Write-Host "   ✓ 已清理: $((Split-Path $path -Leaf))" -ForegroundColor Green
    }
}

# 3. 临时文件 (2.2GB)
Write-Host "`n[3/7] 清理临时文件 (2.2GB)" -ForegroundColor Yellow
$tempPaths = @(
    "C:\Users\lizhi3\.cache",
    "C:\Users\lizhi3\AppData\Local\Temp",
    "C:\Users\lizhi3\AppData\Local\app_shell_cache_6383"
)
foreach ($path in $tempPaths) {
    if (Test-Path $path) {
        Remove-Item $path -Recurse -Force -ErrorAction SilentlyContinue
        if ($path -eq "C:\Users\lizhi3\AppData\Local\Temp") {
            New-Item $path -ItemType Directory -Force | Out-Null
        }
        Write-Host "   ✓ 已清理: $((Split-Path $path -Leaf))" -ForegroundColor Green
    }
}

# 4. Windows更新缓存 (1.8GB)
Write-Host "`n[4/7] 清理Windows更新缓存 (1.8GB)" -ForegroundColor Yellow
Write-Host "   停止Windows Update服务..."
Stop-Service wuauserv -Force -ErrorAction SilentlyContinue
Stop-Service bits -Force -ErrorAction SilentlyContinue
Stop-Service dosvc -Force -ErrorAction SilentlyContinue

$downloadPath = "C:\Windows\SoftwareDistribution\Download"
if (Test-Path $downloadPath) {
    Remove-Item $downloadPath -Recurse -Force -ErrorAction SilentlyContinue
    Write-Host "   ✓ 已清理Windows更新缓存" -ForegroundColor Green
}

Write-Host "   重启Windows Update服务..."
Start-Service bits -ErrorAction SilentlyContinue
Start-Service wuauserv -ErrorAction SilentlyContinue
Start-Service dosvc -ErrorAction SilentlyContinue
Write-Host "   ✓ 服务已重启" -ForegroundColor Green

# 5. 豆包缓存 (0.4GB)
Write-Host "`n[5/7] 清理豆包缓存 (0.4GB)" -ForegroundColor Yellow
$doubaoCache = "C:\Users\lizhi3\AppData\Local\Doubao\User Data\gecko_cache"
if (Test-Path $doubaoCache) {
    Remove-Item $doubaoCache -Recurse -Force -ErrorAction SilentlyContinue
    Write-Host "   ✓ 已清理豆包浏览器缓存" -ForegroundColor Green
}

# 6. 其他小缓存
Write-Host "`n[6/7] 清理其他小缓存" -ForegroundColor Yellow
$edgeCache = "C:\Users\lizhi3\AppData\Local\Microsoft\Edge\User Data\Default\Cache"
if (Test-Path $edgeCache) {
    Remove-Item $edgeCache -Recurse -Force -ErrorAction SilentlyContinue
    Write-Host "   ✓ 已清理Edge缓存" -ForegroundColor Green
}

# 7. 运行磁盘清理
Write-Host "`n[7/7] 启动系统磁盘清理" -ForegroundColor Yellow
Start-Process cleanmgr.exe -ArgumentList "/sagerun:clean" -Wait -WindowStyle Hidden

# 完成清理
Write-Host "`n========================================" -ForegroundColor Cyan
Write-Host "                清理完成！" -ForegroundColor Green
Write-Host "========================================" -ForegroundColor Cyan
Write-Host ""

$after = Get-FreeGB
$freed = $after - $before
Write-Host "开始前: $before GB" -ForegroundColor Yellow
Write-Host "当前:   $after GB" -ForegroundColor Green
Write-Host "释放:   $freed GB" -ForegroundColor Cyan
Write-Host "完成时间: $(Get-Date)" -ForegroundColor Yellow

Write-Host "`n注意事项:" -ForegroundColor Yellow
Write-Host "✓ NVIDIA缓存将在下次游戏运行时自动重建" -ForegroundColor White
Write-Host "✓ 豆包需重启才能完全生效" -ForegroundColor White
Write-Host "✓ 如需释放更多空间，可手动卸载不使用的软件" -ForegroundColor White
Write-Host ""

# 询问是否重启豆包相关进程
Write-Host "建议关闭豆包进程后重启，让清理效果完全生效。" -ForegroundColor Yellow
Read-Host "按Enter键退出..."