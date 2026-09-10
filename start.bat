@echo off
REM RAG 知识库问答系统 - 一键启动脚本 (Windows)
echo ========================================
echo   RAG 知识库问答系统
echo ========================================
echo.

REM 检查 Ollama 是否运行
curl -s http://localhost:11434/api/tags >nul 2>&1
if errorlevel 1 (
    echo [警告] Ollama 服务未运行，请先启动 Ollama
    echo 下载地址: https://ollama.com/download/windows
    echo 拉取模型: ollama pull qwen2.5:7b
    echo.
)

REM 启动后端
echo [1/2] 启动后端服务 (端口 8000)...
cd /d "%~dp0backend"
start "RAG-Backend" cmd /k ".\venv\Scripts\python.exe -m uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload"
echo       后端已启动: http://localhost:8000

REM 等待后端就绪
timeout /t 3 /nobreak >nul

REM 启动前端
echo [2/2] 启动前端服务 (端口 5173)...
cd /d "%~dp0frontend"
start "RAG-Frontend" cmd /k "npx vite --host 0.0.0.0 --port 5173"
echo       前端已启动: http://localhost:5173

echo.
echo ========================================
echo   启动完成！请打开浏览器访问:
echo   http://localhost:5173
echo.
echo   管理员账号: admin / 123456
echo ========================================
pause