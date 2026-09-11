@echo off
REM 启动便携版 Redis（Celery 的任务队列 broker）
REM
REM 便携版不需要管理员权限、不注册系统服务，双击即可运行。
REM 关闭这个窗口 = 停止 Redis。排队中的任务已写入 AOF 文件，
REM 下次启动会自动恢复，不会丢。
REM
REM 【重要】本文件必须保存为 GBK 编码，原因见 enable-wsl.bat 顶部说明。

set REDIS_DIR=D:\tools\redis

if not exist "%REDIS_DIR%\redis-server.exe" (
    echo [错误] 未找到 %REDIS_DIR%\redis-server.exe
    echo 请先下载 Redis-x64-5.0.14.1.zip 并解压到 %REDIS_DIR%
    pause
    exit /b 1
)

echo ============================================
echo  启动 Redis  ^(127.0.0.1:6379^)
echo  数据目录: %REDIS_DIR%\data
echo  关闭本窗口即停止服务
echo ============================================
echo.

cd /d "%REDIS_DIR%"
redis-server.exe redis-rag.conf
