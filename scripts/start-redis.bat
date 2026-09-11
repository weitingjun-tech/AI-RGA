@echo off
REM 启动便携版 Redis（Celery 的 broker）
REM 便携版不需要管理员权限、不注册系统服务，双击即可运行。
REM 关闭这个窗口 = 停止 Redis，正在排队的任务会保留在 AOF 文件里，下次启动自动恢复。

set REDIS_DIR=D:\tools\redis

if not exist "%REDIS_DIR%\redis-server.exe" (
    echo [错误] 未找到 %REDIS_DIR%\redis-server.exe
    echo 请先下载 Redis-x64-5.0.14.1.zip 并解压到 %REDIS_DIR%
    pause
    exit /b 1
)

echo ============================================
echo  启动 Redis (127.0.0.1:6379)
echo  数据目录: %REDIS_DIR%\data
echo  关闭本窗口即停止服务
echo ============================================
echo.

cd /d "%REDIS_DIR%"
redis-server.exe redis-rag.conf
