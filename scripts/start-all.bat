@echo off
REM 一键启动全部服务（四个进程各开一个窗口）
REM
REM 启动顺序有依赖：Redis -> Celery worker -> 后端 -> 前端
REM   Celery worker 启动时会连 broker，Redis 没起来它会一直重试
REM   后端启动时会连 MySQL 并执行数据库迁移
REM
REM 每个服务开独立窗口，便于单独查看日志和单独重启。
REM 关闭某个窗口 = 停止该服务。
REM
REM 【重要】本文件必须保存为 GBK 编码。cmd.exe 按系统 ANSI 代码页读 .bat，
REM   中文 Windows 下是 GBK；存成 UTF-8 会让乱码破坏批处理语法结构。

set ROOT=%~dp0..

echo ============================================================
echo  RAG 知识库问答系统 - 启动全部服务
echo ============================================================
echo.

REM --- 0. 前置检查 ---
echo [检查] MySQL ...
netstat -ano | findstr ":3306" | findstr "LISTENING" >nul
if errorlevel 1 (
    echo    [警告] 3306 端口未监听，MySQL 可能没启动
    echo           后端会启动失败，请先启动 MySQL
) else (
    echo    [OK] MySQL 运行中
)

echo [检查] Ollama ...
netstat -ano | findstr ":11434" | findstr "LISTENING" >nul
if errorlevel 1 (
    echo    [警告] 11434 端口未监听，Ollama 没启动
    echo           系统能检索但无法生成回答，请运行: ollama serve
) else (
    echo    [OK] Ollama 运行中
)
echo.

REM --- 1. Redis ---
echo [1/4] 启动 Redis ...
start "RAG-Redis" cmd /k "%ROOT%\scripts\start-redis.bat"
timeout /t 3 /nobreak >nul

REM --- 2. Celery worker ---
echo [2/4] 启动 Celery worker ...
start "RAG-Celery" cmd /k "%ROOT%\scripts\start-celery.bat"
timeout /t 3 /nobreak >nul

REM --- 3. 后端 ---
echo [3/4] 启动后端 ...
start "RAG-Backend" cmd /k "cd /d %ROOT%\backend && venv\Scripts\python.exe -m uvicorn app.main:app --host 0.0.0.0 --port 8000"
echo       等待模型加载（首次约 20-30 秒）...
timeout /t 25 /nobreak >nul

REM --- 4. 前端 ---
echo [4/4] 启动前端 ...
start "RAG-Frontend" cmd /k "cd /d %ROOT%\frontend && npm run dev"
timeout /t 12 /nobreak >nul

echo.
echo ============================================================
echo  启动完成，验证中 ...
echo ============================================================
echo.

curl -s -o nul -w "  后端      HTTP %%{http_code}\n" http://127.0.0.1:8000/api/health
curl -s -o nul -w "  前端      HTTP %%{http_code}\n" http://127.0.0.1:5173/
echo.
echo  就绪探针（逐项检查依赖）:
curl -s http://127.0.0.1:8000/api/health/ready
echo.
echo.
echo  访问地址: http://localhost:5173
echo  默认账号: admin / 123456
echo.
echo  关闭某个服务的窗口 = 停止该服务。
echo.
pause
