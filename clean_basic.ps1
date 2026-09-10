# 基础清理脚本（跳过权限检查）
$ErrorActionPreference = "SilentlyContinue"

Write-Host "========================================"
Write-Host "         C盘基础清理工具"
Write-Host "========================================"
Write-Host ""

# 获取空闲空间
function Get-FreeGB {
    return [math]::Round((Get-PSDrive C).Free/1GB, 2)
}

$before = Get-FreeGB
Write-Host "开始前空闲空间: $before GB"
Write-Host "开始时间: $(Get-Date)"
Write-Host ""

# 1. NVIDIA着色器缓存 - 最大！
Write-Host "[1/7] 清理NVIDIA着色器缓存 (18GB)"
$nvidiaCache = "C:\Users\lizhi3\AppData\Local\NVIDIA\DXCache"
if (Test-Path $nvidiaCache) {
    Remove-Item $nvidiaCache -Recurse -Force -ErrorAction SilentlyContinue
    Write-Host "   已清理NVIDIA DXCache"
}

$nvidiaGl = "C:\Users\lizhi3\AppData\Local\NVIDIA\GLCache"
if (Test-Path $nvidiaGl) {
    Remove-Item $nvidiaGl -Recurse -Force -ErrorAction SilentlyContinue
    Write-Host "   已清理NVIDIA GLCache"
}

# 2. 剪映缓存
Write-Host "`n[2/7] 清理剪映缓存 (2.1GB)"
$jianyingCache = "C:\Users\lizhi3\AppData\Local\JianyingPro\User Data\Cache"
if (Test-Path $jianyingCache) {
    Remove-Item $jianyingCache -Recurse -Force -ErrorAction SilentlyContinue
    Write-Host "   已清理JianyingPro缓存"
}

# 3. 临时文件
Write-Host "`n[3/7] 清理临时文件 (2.2GB)"
$tempDirs = @(
    "C:\Users\lizhi3\.cache",
    "C:\Users\lizhi3\AppData\Local\app_shell_cache_6383"
)
foreach ($dir in $tempDirs) {
    if (Test-Path $dir) {
        Remove-Item $dir -Recurse -Force -ErrorAction SilentlyContinue
        Write-Host "   已清理临时文件夹"
    }
}

$tempDir = "C:\Users\lizhi3\AppData\Local\Temp"
if (Test-Path $tempDir) {
    Remove-Item $tempDir -Recurse -Force -ErrorAction SilentlyContinue
    New-Item $tempDir -ItemType Directory -Force | Out-Null
    Write-Host "   已重建临时文件夹"
}

# 4. 豆包缓存
Write-Host "`n[4/7] 清理豆包缓存 (0.4GB)"
$doubaoCache = "C:\Users\lizhi3\AppData\Local\Doubao\User Data\gecko_cache"
if (Test-Path $doubaoCache) {
    Remove-Item $doubaoCache -Recurse -Force -ErrorAction SilentlyContinue
    Write-Host "   已清理豆包缓存"
}

# 5. 开发包缓存
Write-Host "`n[5/7] 清理开发包缓存"
$pythonCache = "C:\Users\lizhi3\AppData\Local\pip\Cache"
if (Test-Path $pythonCache) {
    Remove-Item $pythonCache -Recurse -Force -ErrorAction SilentlyContinue
    Write-Host "   已清理pip缓存"
}

# 6. 其他应用缓存
Write-Host "`n[6/7] 清理应用缓存"
$otherCaches = @(
    "C:\Users\lizhi3\AppData\Local\Doubao\User Data\Cache",
    "C:\Users\lizhi3\AppData\Local\Doubao\User Data\Code Cache",
    "C:\Users\lizhi3\AppData\Local\Microsoft\Edge\User Data\Default\Cache"
)
foreach ($cache in $otherCaches) {
    if (Test-Path $cache) {
        Remove-Item $cache -Recurse -Force -ErrorAction SilentlyContinue
        Write-Host "   已清理应用缓存"
    }
}

# 完成清理
Write-Host "`n========================================"
Write-Host "                基础清理完成！"
Write-Host "========================================"
Write-Host ""

$after = Get-FreeGB
$freed = $after - $before
Write-Host "开始前: $before GB" -ForegroundColor Yellow
Write-Host "当前:   $after GB" -ForegroundColor Green
Write-Host "释放:   $freed GB" -ForegroundColor Cyan
Write-Host "完成时间: $(Get-Date)" -ForegroundColor Yellow

Write-Host "`n已清理的文件（需要管理员权限才能清理的未执行）:"
Write-Host "- Windows更新缓存 (1.8GB)"
Write-Host "- NVIDIA GLCache (如果有)"