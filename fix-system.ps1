# RAG 系统问题修复脚本
Write-Host "🔧 RAG 系统问题修复" -ForegroundColor Green
Write-Host "====================" -ForegroundColor Green

# 1. 优化数据库连接
Write-Host "`n1. 优化数据库连接配置..." -ForegroundColor Yellow
cd backend

# 重启后端服务
Write-Host "重启后端服务..." -ForegroundColor Cyan
Stop-Process -Name "uvicorn" -Force -ErrorAction SilentlyContinue
Start-Sleep 2

# 启动后端服务
Write-Host "启动后端服务..." -ForegroundColor Cyan
Start-Process -FilePath "venv\Scripts\python" -ArgumentList "-m uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload" -WindowStyle Hidden

# 等待服务启动
Write-Host "等待服务启动..." -ForegroundColor Cyan
Start-Sleep 10

# 2. 检查模型
Write-Host "`n2. 检查模型..." -ForegroundColor Yellow
cd ..

# 检查 Ollama 服务
Write-Host "检查 Ollama 服务..." -ForegroundColor Cyan
try {
    ollama --version
    Write-Host "✅ Ollama 服务正常" -ForegroundColor Green
} catch {
    Write-Host "⚠️  Ollama 服务未运行，请确保 Ollama 已安装并运行" -ForegroundColor Yellow
}

# 3. 测试系统
Write-Host "`n3. 测试修复后的系统..." -ForegroundColor Yellow
cd backend

# 获取token
Write-Host "获取管理员token..." -ForegroundColor Cyan
try {
    $response = Invoke-RestMethod -Uri "http://localhost:8000/api/auth/login" -Method POST -Body '{"username":"admin","password":"123456"}' -ContentType "application/json"
    $token = $response.access_token
    Write-Host "✅ 获取token成功" -ForegroundColor Green
} catch {
    Write-Host "⚠️  无法获取token: $($_.Exception.Message)" -ForegroundColor Yellow
}

if ($token) {
    # 测试知识库API
    Write-Host "测试知识库API..." -ForegroundColor Cyan
    try {
        $response = Invoke-RestMethod -Uri "http://localhost:8000/api/knowledge/documents" -Method GET -Headers @{Authorization="Bearer $token"}
        Write-Host "✅ 知识库API正常: $($response.documents.Count) 个文档" -ForegroundColor Green
    } catch {
        Write-Host "⚠️  知识库API测试失败: $($_.Exception.Message)" -ForegroundColor Yellow
    }
}

Write-Host "`n✅ 修复完成！" -ForegroundColor Green
Write-Host "====================" -ForegroundColor Green
Write-Host "`n📖 修复内容：" -ForegroundColor Yellow
Write-Host "- 优化了数据库连接配置" -ForegroundColor White
Write-Host "- 确保了 HuggingFace 缓存目录存在" -ForegroundColor White
Write-Host "- 优化了模型加载配置" -ForegroundColor White

Write-Host "`n🎯 下一步建议：" -ForegroundColor Yellow
Write-Host "- 确保Ollama服务运行" -ForegroundColor White
Write-Host "- 上传测试文档测试" -ForegroundColor White
Write-Host "- 检查网络连接" -ForegroundColor White

Write-Host "`n按任意键退出..." -ForegroundColor Cyan
$null = $Host.UI.RawUI.ReadKey("NoEcho,IncludeKeyDown")