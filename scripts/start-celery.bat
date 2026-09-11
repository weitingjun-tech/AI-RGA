@echo off
REM 启动 Celery worker（文档处理后台任务）
REM
REM 注意 --pool=solo：
REM   Celery 默认用 prefork 进程池，在 Windows 上与 asyncio 事件循环冲突会直接报错。
REM   --pool=solo 表示单进程串行执行，是 Windows 下的唯一可用选项。
REM   Linux/macOS 不需要这个参数，可以换成 --concurrency=N 做并发。

cd /d "%~dp0..\backend"

echo ============================================
echo  启动 Celery worker
echo  任务: documents.process（文档解析 + 向量化）
echo  关闭本窗口即停止 worker
echo ============================================
echo.

REM 先确认 Redis 是否可达，避免 worker 起来后连不上 broker 白白空转
venv\Scripts\python.exe -c "import redis; redis.Redis.from_url('redis://localhost:6379/0', socket_connect_timeout=2).ping()" 2>nul
if errorlevel 1 (
    echo [警告] 连不上 Redis ^(localhost:6379^)
    echo        请先运行 scripts\start-redis.bat
    echo.
    echo        继续启动的话，文档处理会降级为本地线程模式，
    echo        进程重启会丢失未完成的任务。
    echo.
    pause
)

venv\Scripts\python.exe -m celery -A app.celery_app:celery_app worker --loglevel=info --pool=solo
