@echo off
chcp 65001 >nul
echo ========================================
echo       C盘清理工具 v1.0
echo ========================================
echo.
echo 正在检查管理员权限...
net session >nul 2>&1
if %errorlevel% == 0 (
    echo [✓] 已获得管理员权限
) else (
    echo [!] 请右键此文件选择"以管理员身份运行"
    echo      或在管理员cmd窗口中执行
    echo.
    pause
    exit /b 1
)

echo.
echo ========================================
echo 释放空间: 约24.5 GB
echo ========================================

:: 获取开始前的空闲空间
powershell -Command "$before = [math]::Round((Get-PSDrive C).Free/1GB, 2); Write-Output $before"
set /p before_space=输入开始前的空闲空间(GB):
echo 开始时间: %date% %time%

echo.
echo [1/7] 清理NVIDIA着色器缓存 (18GB)...
if exist "C:\Users\lizhi3\AppData\Local\NVIDIA\DXCache" (
    rd /s /q "C:\Users\lizhi3\AppData\Local\NVIDIA\DXCache" 2>nul
    echo   ✓ 已清理DXCache
)
if exist "C:\Users\lizhi3\AppData\Local\NVIDIA\GLCache" (
    rd /s /q "C:\Users\lizhi3\AppData\Local\NVIDIA\GLCache" 2>nul
    echo   ✓ 已清理GLCache
)

echo.
echo [2/7] 清理剪映缓存 (2.1GB)...
if exist "C:\Users\lizhi3\AppData\Local\JianyingPro\User Data\Cache" (
    rd /s /q "C:\Users\lizhi3\AppData\Local\JianyingPro\User Data\Cache" 2>nul
    echo   ✓ 已清理JianyingPro缓存
)
if exist "C:\Users\lizhi3\AppData\Local\JianyingPro\User Data\Log" (
    rd /s /q "C:\Users\lizhi3\AppData\Local\JianyingPro\User Data\Log" 2>nul
    echo   ✓ 已清理JianyingPro日志
)
if exist "C:\Users\lizhi3\AppData\Local\JianyingPro\User Data\Crash" (
    rd /s /q "C:\Users\lizhi3\AppData\Local\JianyingPro\User Data\Crash" 2>nul
    echo   ✓ 已清理JianyingPro崩溃数据
)
if exist "C:\Users\lizhi3\AppData\Local\JianyingPro\User Data\Tracking" (
    rd /s /q "C:\Users\lizhi3\AppData\Local\JianyingPro\User Data\Tracking" 2>nul
    echo   ✓ 已清理JianyingPro跟踪数据
)

echo.
echo [3/7] 清理临时文件 (2.2GB)...
if exist "C:\Users\lizhi3\.cache" (
    rd /s /q "C:\Users\lizhi3\.cache" 2>nul
    echo   ✓ 已清理用户缓存
)
if exist "C:\Users\lizhi3\AppData\Local\Temp" (
    rd /s /q "C:\Users\lizhi3\AppData\Local\Temp" 2>nul
    mkdir "C:\Users\lizhi3\AppData\Local\Temp" >nul 2>&1
    echo   ✓ 已清理并重建临时文件夹
)
if exist "C:\Users\lizhi3\AppData\Local\app_shell_cache_6383" (
    rd /s /q "C:\Users\lizhi3\AppData\Local\app_shell_cache_6383" 2>nul
    echo   ✓ 已清理Shell缓存
)

echo.
echo [4/7] 清理Windows更新缓存 (1.8GB) - 停止服务中...
net stop wuauserv /y >nul 2>&1
net stop bits /y >nul 2>&1
net stop dosvc /y >nul 2>&1

if exist "C:\Windows\SoftwareDistribution\Download" (
    rd /s /q "C:\Windows\SoftwareDistribution\Download" 2>nul
    echo   ✓ 已清理Windows更新缓存
)

echo 重启服务...
net start wuauserv >nul 2>&1
net start bits >nul 2>&1
net start dosvc >nul 2>&1
echo   ✓ 服务已重启

echo.
echo [5/7] 清理豆包缓存 (0.4GB)...
if exist "C:\Users\lizhi3\AppData\Local\Doubao\User Data\gecko_cache" (
    rd /s /q "C:\Users\lizhi3\AppData\Local\Doubao\User Data\gecko_cache" 2>nul
    echo   ✓ 已清理豆包浏览器缓存
)

echo.
echo [6/7] 清理其他小缓存...
if exist "C:\Users\lizhi3\AppData\Local\Microsoft\Edge\User Data\Default\Cache" (
    rd /s /q "C:\Users\lizhi3\AppData\Local\Microsoft\Edge\User Data\Default\Cache" 2>nul
    echo   ✓ 已清理Edge缓存 (如果存在)
)

echo.
echo [7/7] 清理系统垃圾...
cleanmgr.exe /sagerun:clean >nul 2>&1
echo   ✓ 已启动磁盘清理 (请等待完成)

echo.
echo ========================================
echo 清理完成！
echo ========================================
echo.
powershell -Command "$after = [math]::Round((Get-PSDrive C).Free/1GB, 2); Write-Output '当前空闲空间:' $after 'GB'"
echo 开始时间: %date% %time%
echo.
echo 注意事项:
echo 1. NVIDIA缓存将在下次游戏运行时自动重建
echo 2. 豆包需重启才能完全生效
echo 3. 如需释放更多空间，可手动卸载不使用的软件
echo.
pause