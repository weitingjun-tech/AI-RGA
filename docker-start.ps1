# RAG 知识库问答系统 - Docker 快速启动
# 使用方法：PowerShell -ExecutionPolicy Bypass -File docker-start.ps1

Write-Host "🐳 RAG 知识库问答系统 - Docker 部署" -ForegroundColor Green
Write-Host "========================================" -ForegroundColor Green

# 检查 Docker 是否运行
if (-not (Get-Command docker -ErrorAction SilentlyContinue)) {
    Write-Error "❌ 未找到 Docker，请先安装 Docker"
    exit 1
}

# 检查 Docker 是否运行
try {
    $dockerInfo = docker info
    if (-not $dockerInfo) {
        throw "Docker 未运行"
    }
} catch {
    Write-Error "❌ Docker 未运行，请启动 Docker Desktop"
    exit 1
}

Write-Host "✅ Docker 已就绪" -ForegroundColor Green

# 停止现有容器（如果存在）
Write-Host "`n🛑 停止现有容器..." -ForegroundColor Yellow
docker-compose down -v

# 构建并启动服务
Write-Host "`n🏗️  构建并启动服务..." -ForegroundColor Yellow
docker-compose up --build -d

# 等待服务启动
Write-Host "`n⏳ 等待服务启动..." -ForegroundColor Yellow
Start-Sleep 10

# 检查服务状态
Write-Host "`n📊 检查服务状态..." -ForegroundColor Yellow
docker-compose ps

# 显示访问信息
Write-Host "`n✅ 服务启动完成！" -ForegroundColor Green
Write-Host "========================================" -ForegroundColor Green
Write-Host "`n📖 访问地址：" -ForegroundColor Yellow
Write-Host "- 前端应用: http://localhost:5173" -ForegroundColor White
Write-Host "- 后端 API: http://localhost:8001" -ForegroundColor White
Write-Host "- API 文档: http://localhost:8001/docs" -ForegroundColor White
Write-Host "- ChromaDB: http://localhost:8000" -ForegroundColor White
Write-Host "- MySQL: localhost:3306" -ForegroundColor White

Write-Host "`n🎯 默认账号：" -ForegroundColor Yellow
Write-Host "- 管理员: admin / 123456" -ForegroundColor White
Write-Host "- 普通用户: test / test123" -ForegroundColor White

Write-Host "`n📋 查看日志：" -ForegroundColor Yellow
Write-Host "docker-compose logs -f" -ForegroundColor White
Write-Host "docker-compose logs -f backend" -ForegroundColor White
Write-Host "docker-compose logs -f frontend" -ForegroundColor White

Write-Host "`n🛑 停止服务：" -ForegroundColor Yellow
Write-Host "docker-compose down" -ForegroundColor White

Write-Host "`n按任意键查看实时日志..." -ForegroundColor Cyan
$null = $Host.UI.RawUI.ReadKey("NoEcho,IncludeKeyDown")

# 显示实时日志
Write-Host "`n📄 实时日志：" -ForegroundColor Yellow
docker-compose logs -f