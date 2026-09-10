# RAG 系统测试脚本
Write-Host "🧪 RAG 知识库问答系统 - 功能测试" -ForegroundColor Green
Write-Host "================================" -ForegroundColor Green

# 测试后端服务
Write-Host "`n📡 测试后端服务..." -ForegroundColor Yellow
cd backend

# 等待依赖安装完成
Write-Host "等待依赖安装完成..." -ForegroundColor Cyan
Start-Sleep 30

# 激活虚拟环境
Write-Host "激活虚拟环境..." -ForegroundColor Cyan
& ./venv/Scripts/Activate.ps1

# 测试导入主要模块
Write-Host "`n📦 测试模块导入..." -ForegroundColor Cyan
try {
    python -c "import app.main; print('✅ 主模块导入成功')"
    python -c "from app.database import engine; print('✅ 数据库连接测试成功')"
    python -c "from app.services.rag_service import get_llm; print('✅ RAG服务导入成功')"
} catch {
    Write-Error "❌ 模块导入失败"
    exit 1
}

# 启动后端服务（后台）
Write-Host "`n🚀 启动后端服务..." -ForegroundColor Cyan
$backendProcess = Start-Process -FilePath "python" -ArgumentList "-m uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload" -PassThru -RedirectStandardOutput "backend.log" -RedirectStandardError "backend-error.log"

# 等待后端启动
Write-Host "等待后端服务启动..." -ForegroundColor Cyan
Start-Sleep 10

# 测试 API 健康检查
Write-Host "`n🔍 测试 API 端点..." -ForegroundColor Cyan
try {
    $healthResponse = Invoke-RestMethod -Uri "http://localhost:8000/api/health" -Method GET
    Write-Host "✅ 健康检查: $($healthResponse.status)" -ForegroundColor Green
} catch {
    Write-Error "❌ 健康检查失败: $($_.Exception.Message)"
}

# 测试认证 API
Write-Host "`n🔐 测试认证功能..." -ForegroundColor Cyan
try {
    # 测试登录
    $loginBody = @{
        username = "admin"
        password = "123456"
    } | ConvertTo-Json

    $loginResponse = Invoke-RestMethod -Uri "http://localhost:8000/api/auth/login" -Method POST -Body $loginBody -ContentType "application/json"
    Write-Host "✅ 登录成功: $($loginResponse.username)" -ForegroundColor Green
    $token = $loginResponse.access_token
} catch {
    Write-Error "❌ 登录测试失败: $($_.Exception.Message)"
}

# 测试会话 API
Write-Host "`n💬 测试会话管理..." -ForegroundColor Cyan
if ($token) {
    try {
        $headers = @{
            "Authorization" = "Bearer $token"
            "Content-Type" = "application/json"
        }

        # 创建会话
        $createConvResponse = Invoke-RestMethod -Uri "http://localhost:8000/api/chat/conversations" -Method POST -Headers $headers
        Write-Host "✅ 创建会话成功: $($createConvResponse.id)" -ForegroundColor Green

        # 获取会话列表
        $convListResponse = Invoke-RestMethod -Uri "http://localhost:8000/api/chat/conversations" -Method GET -Headers $headers
        Write-Host "✅ 获取会话列表成功: $($convListResponse.conversations.Count) 个会话" -ForegroundColor Green
    } catch {
        Write-Error "❌ 会话测试失败: $($_.Exception.Message)"
    }
}

# 启动前端服务
Write-Host "`n🎨 启动前端服务..." -ForegroundColor Yellow
cd ../frontend

Write-Host "安装前端依赖..." -ForegroundColor Cyan
npm install

Write-Host "启动前端开发服务器..." -ForegroundColor Cyan
$frontendProcess = Start-Process -FilePath "npm" -ArgumentList "run dev" -PassThru -RedirectStandardOutput "frontend.log" -RedirectStandardError "frontend-error.log"

# 等待前端启动
Write-Host "等待前端服务启动..." -ForegroundColor Cyan
Start-Sleep 15

# 测试前端页面
Write-Host "`n🌐 测试前端页面..." -ForegroundColor Cyan
try {
    $frontendResponse = Invoke-RestMethod -Uri "http://localhost:5173" -Method HEAD
    Write-Host "✅ 前端服务正常" -ForegroundColor Green
} catch {
    Write-Warning "⚠️  前端服务可能还在启动中"
}

# 显示访问信息
Write-Host "`n✅ 测试完成！" -ForegroundColor Green
Write-Host "================================" -ForegroundColor Green
Write-Host "`n📖 访问地址：" -ForegroundColor Yellow
Write-Host "- 前端应用: http://localhost:5173" -ForegroundColor White
Write-Host "- 后端 API: http://localhost:8000" -ForegroundColor White
Write-Host "- API 文档: http://localhost:8000/docs" -ForegroundColor White

Write-Host "`n🎯 默认账号：" -ForegroundColor Yellow
Write-Host "- 管理员: admin / 123456" -ForegroundColor White
Write-Host "- 普通用户: test / test123" -ForegroundColor White

Write-Host "`n📋 测试日志：" -ForegroundColor Yellow
Write-Host "- 后端日志: backend.log" -ForegroundColor White
Write-Host "- 前端日志: frontend.log" -ForegroundColor White

Write-Host "`n💡 手动测试步骤：" -ForegroundColor Yellow
Write-Host "1. 打开浏览器访问 http://localhost:5173" -ForegroundColor White
Write-Host "2. 使用 admin/123456 登录" -ForegroundColor White
Write-Host "3. 上传测试文档（商品信息）" -ForegroundColor White
Write-Host "4. 测试问答功能" -ForegroundColor White

Write-Host "`n按任意键停止服务并退出..." -ForegroundColor Cyan
$null = $Host.UI.RawUI.ReadKey("NoEcho,IncludeKeyDown")

# 停止服务
Write-Host "`n🛑 停止服务..." -ForegroundColor Yellow
Stop-Process -Id $backendProcess.Id -Force
Stop-Process -Id $frontendProcess.Id -Force

Write-Host "服务已停止" -ForegroundColor Green