# RAG 知识库问答系统 - 自动部署脚本
# 使用方法：PowerShell -ExecutionPolicy Bypass -File deploy.ps1

Write-Host "🚀 RAG 知识库问答系统 - 自动部署" -ForegroundColor Green
Write-Host "========================================" -ForegroundColor Green

# 检查管理员权限
if (-NOT ([Security.Principal.WindowsPrincipal][Security.Principal.WindowsIdentity]::GetCurrent()).IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)) {
    Write-Warning "请以管理员身份运行此脚本"
    Read-Host "按任意键退出"
    exit
}

# 1. 检查并安装依赖
Write-Host "`n📦 检查系统依赖..." -ForegroundColor Yellow

# 检查 Python
if (-not (Get-Command python -ErrorAction SilentlyContinue)) {
    Write-Error "❌ 未找到 Python，请先安装 Python 3.11+"
    exit 1
}
Write-Host "✅ Python 版本: $(python --version)"

# 检查 Node.js
if (-not (Get-Command node -ErrorAction SilentlyContinue)) {
    Write-Error "❌ 未找到 Node.js，请先安装 Node.js 18+"
    exit 1
}
Write-Host "✅ Node.js 版本: $(node --version)"

# 检查 MySQL
try {
    $mysqlResult = mysql --version
    Write-Host "✅ MySQL: $mysqlResult"
} catch {
    Write-Warning "⚠️  未检测到 MySQL，请确保 MySQL 8.0 已运行"
}

# 2. 创建虚拟环境
Write-Host "`n🔧 设置后端环境..." -ForegroundColor Yellow
cd backend

# 创建虚拟环境（如果不存在）
if (-not (Test-Path "venv")) {
    Write-Host "创建 Python 虚拟环境..."
    python -m venv venv
}

# 激活虚拟环境
.\venv\Scripts\activate

# 安装 Python 依赖
Write-Host "安装 Python 依赖包..."
pip install -r requirements.txt

# 3. 配置环境变量
Write-Host "`n⚙️  配置环境变量..." -ForegroundColor Yellow

# 检查 .env 文件
if (-not (Test-Path ".env")) {
    Write-Host "创建 .env 配置文件..."
    @"
# RAG 知识库问答系统 - 环境变量配置
# MySQL
MYSQL_HOST=localhost
MYSQL_PORT=3306
MYSQL_USER=root
MYSQL_PASSWORD=root
MYSQL_DATABASE=rag_knowledge_base

# JWT
JWT_SECRET=my-secret-key-change-in-production
JWT_ACCESS_EXPIRE_MINUTES=120
JWT_REFRESH_EXPIRE_DAYS=7

# Ollama
OLLAMA_BASE_URL=http://localhost:11434
OLLAMA_MODEL=qwen2.5:7b

# Embedding
EMBEDDING_MODEL=BAAI/bge-small-zh-v1.5
EMBEDDING_DEVICE=cpu
HF_HOME=D:/mydo/huggingface_cache

# ChromaDB
CHROMA_PERSIST_DIR=./chroma_data
CHROMA_COLLECTION_NAME=ecommerce_knowledge

# 分块参数
CHUNK_SIZE=500
CHUNK_OVERLAP=50
RETRIEVAL_TOP_K=5
RELEVANCE_THRESHOLD=0.3

# 缓存
CACHE_TTL=300
CACHE_MAX_SIZE=128

# 文件上传
UPLOAD_DIR=./uploads
MAX_UPLOAD_SIZE=20

# CORS
CORS_ORIGINS=http://localhost:5173,http://localhost:3000
"@ | Out-File -FilePath ".env" -Encoding UTF8
}

# 4. 设置前端
Write-Host "`n🎨 设置前端环境..." -ForegroundColor Yellow
cd ..

cd frontend

# 安装前端依赖
Write-Host "安装前端依赖包..."
npm install

# 5. 创建启动脚本
Write-Host "`n📝 创建启动脚本..." -ForegroundColor Yellow

# 后端启动脚本
@"
@echo off
title RAG Backend Server
cd /d "%~dp0\backend"
call .\venv\Scripts\activate
python -m uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload
pause
"@ | Out-File -FilePath "start-backend.bat" -Encoding ASCII

# 前端启动脚本
@"
@echo off
title RAG Frontend Server
cd /d "%~dp0\frontend"
npm run dev
pause
"@ | Out-File -FilePath "start-frontend.bat" -Encoding ASCII

# 一键启动脚本
@"
@echo off
echo 启动 RAG 知识库问答系统...
echo.
echo 正在启动后端服务...
start "Backend" cmd /k "start-backend.bat"
timeout /t 3 /nobreak > nul

echo 正在启动前端服务...
start "Frontend" cmd /k "start-frontend.bat"
echo.
echo 系统启动中...
echo 后端地址: http://localhost:8000
echo 前端地址: http://localhost:5173
echo.
echo 按任意键退出...
pause > nul
"@ | Out-File -FilePath "start-system.bat" -Encoding ASCII

# 6. 创建数据库初始化脚本
Write-Host "`n💾 创建数据库脚本..." -ForegroundColor Yellow
cd ..

@"
-- RAG 知识库问答系统 - 数据库初始化脚本
-- 创建数据库
CREATE DATABASE IF NOT EXISTS rag_knowledge_base CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;

-- 使用数据库
USE rag_knowledge_base;

-- 创建用户表
CREATE TABLE IF NOT EXISTS users (
    id INT PRIMARY KEY AUTO_INCREMENT,
    username VARCHAR(50) UNIQUE NOT NULL,
    password_hash VARCHAR(255) NOT NULL,
    role ENUM('admin', 'user') DEFAULT 'user',
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP
);

-- 创建会话表
CREATE TABLE IF NOT EXISTS conversations (
    id INT PRIMARY KEY AUTO_INCREMENT,
    user_id INT NOT NULL,
    title VARCHAR(200) NOT NULL,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE
);

-- 创建消息表
CREATE TABLE IF NOT EXISTS messages (
    id INT PRIMARY KEY AUTO_INCREMENT,
    conversation_id INT NOT NULL,
    role ENUM('user', 'assistant') NOT NULL,
    content TEXT NOT NULL,
    sources JSON,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (conversation_id) REFERENCES conversations(id) ON DELETE CASCADE
);

-- 创建文档表
CREATE TABLE IF NOT EXISTS documents (
    id INT PRIMARY KEY AUTO_INCREMENT,
    filename VARCHAR(255) NOT NULL,
    file_type VARCHAR(10) NOT NULL,
    file_size BIGINT,
    status ENUM('processing', 'ready', 'error') DEFAULT 'processing',
    chunk_count INT DEFAULT 0,
    uploaded_by INT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    FOREIGN KEY (uploaded_by) REFERENCES users(id) ON DELETE SET NULL
);

-- 插入默认管理员账号
INSERT INTO users (username, password_hash, role) VALUES
('admin', '$2b$12$LQv3c1yqBWVHxkd0LHAkCOYz6TtxMQJqhN8/LewDrPNAXfL/mhZy', 'admin')
ON DUPLICATE KEY UPDATE username = username;

-- 查询确认
SELECT '数据库初始化完成' as message;
SELECT '默认管理员账号: admin / 123456' as admin_info;
"@ | Out-File -FilePath "init-database.sql" -Encoding UTF8

# 7. 完成部署
Write-Host "`n✅ 部署完成！" -ForegroundColor Green
Write-Host "========================================" -ForegroundColor Green
Write-Host "`n📋 后续步骤：" -ForegroundColor Yellow
Write-Host "1. 确保 MySQL 服务正在运行" -ForegroundColor White
Write-Host "2. 确保 Ollama 服务正在运行" -ForegroundColor White
Write-Host "3. 运行 init-database.sql 初始化数据库" -ForegroundColor White
Write-Host "4. 双击 start-system.bat 启动系统" -ForegroundColor White
Write-Host "5. 访问 http://localhost:5173" -ForegroundColor White

Write-Host "`n📖 相关文档：" -ForegroundColor Yellow
Write-Host "- 启动指南.md: 详细的启动步骤" -ForegroundColor White
Write-Host "- 测试文档.md: 系统测试方法" -ForegroundColor White
Write-Host "- README.md: 项目说明" -ForegroundColor White

Write-Host "`n🎯 默认账号：" -ForegroundColor Yellow
Write-Host "- 管理员: admin / 123456" -ForegroundColor White
Write-Host "- 普通用户: test / test123" -ForegroundColor White

Write-Host "`n按任意键退出..." -ForegroundColor Cyan
$null = $Host.UI.RawUI.ReadKey("NoEcho,IncludeKeyDown")