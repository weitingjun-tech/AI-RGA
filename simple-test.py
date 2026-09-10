#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
RAG 系统功能测试脚本
"""

import sys
import os
import time
import requests
import json
from pathlib import Path

# 添加后端路径
sys.path.append(str(Path(__file__).parent / "backend"))

def test_backend_import():
    """测试后端模块导入"""
    print("[测试] 后端模块导入...")
    try:
        from app.main import app
        from app.database import engine
        from app.services.rag_service import get_llm
        print("[OK] 后端模块导入成功")
        return True
    except Exception as e:
        print(f"[错误] 后端模块导入失败: {e}")
        return False

def test_database_connection():
    """测试数据库连接"""
    print("[测试] 数据库连接...")
    try:
        from app.database import SessionLocal
        db = SessionLocal()
        # 简单查询
        result = db.execute("SELECT 1").fetchone()
        if result:
            print("[OK] 数据库连接成功")
            db.close()
            return True
        else:
            print("[错误] 数据库查询失败")
            return False
    except Exception as e:
        print(f"[错误] 数据库连接失败: {e}")
        return False

def test_auth_api():
    """测试认证API"""
    print("[测试] 认证API...")
    try:
        # 测试登录
        login_data = {
            "username": "admin",
            "password": "123456"
        }
        response = requests.post(
            "http://localhost:8000/api/auth/login",
            json=login_data
        )
        if response.status_code == 200:
            token = response.json().get("access_token")
            print("[OK] 登录成功")
            return token
        else:
            print(f"[错误] 登录失败: {response.status_code}")
            return None
    except Exception as e:
        print(f"[错误] 认证API测试失败: {e}")
        return None

def test_chat_api(token):
    """测试聊天API"""
    if not token:
        print("[跳过] 聊天API测试（无token）")
        return False

    print("[测试] 聊天API...")
    headers = {"Authorization": f"Bearer {token}"}

    try:
        # 创建会话
        response = requests.post(
            "http://localhost:8000/api/chat/conversations",
            headers=headers
        )
        if response.status_code == 200:
            conv_id = response.json().get("id")
            print(f"[OK] 创建会话成功: {conv_id}")
            return True
        else:
            print(f"[错误] 创建会话失败: {response.status_code}")
            return False
    except Exception as e:
        print(f"[错误] 聊天API测试失败: {e}")
        return False

def test_knowledge_api(token):
    """测试知识库API（仅管理员）"""
    if not token:
        print("[跳过] 知识库API测试（无token）")
        return False

    print("[测试] 知识库API...")
    headers = {"Authorization": f"Bearer {token}"}

    try:
        # 获取文档列表
        response = requests.get(
            "http://localhost:8000/api/knowledge/documents",
            headers=headers
        )
        if response.status_code == 200:
            docs = response.json().get("documents", [])
            print(f"[OK] 获取文档列表成功: {len(docs)} 个文档")
            return True
        else:
            print(f"[错误] 获取文档列表失败: {response.status_code}")
            return False
    except Exception as e:
        print(f"[错误] 知识库API测试失败: {e}")
        return False

def main():
    """主测试函数"""
    print("=" * 50)
    print("RAG 知识库问答系统 - 功能测试")
    print("=" * 50)

    # 检查服务是否运行
    print("[检查] 检查后端服务...")
    try:
        response = requests.get("http://localhost:8000/api/health", timeout=5)
        print("[OK] 后端服务正在运行")
    except:
        print("[错误] 后端服务未运行，请先启动后端服务")
        print("启动命令: cd backend && venv/Scripts/python -m uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload")
        return

    # 执行测试
    tests = [
        ("后端模块导入", test_backend_import),
        ("数据库连接", test_database_connection),
        ("认证API", lambda: test_auth_api()),
        ("聊天API", lambda: test_chat_api(test_auth_api())),
        ("知识库API", lambda: test_knowledge_api(test_auth_api())),
    ]

    results = []
    for name, test_func in tests:
        print(f"\n{'-' * 30}")
        result = test_func()
        results.append((name, result))

    # 显示结果
    print(f"\n{'=' * 50}")
    print("测试结果汇总:")
    print("=" * 50)

    passed = 0
    for name, result in results:
        status = "[通过]" if result else "[失败]"
        print(f"{status} {name}")
        if result:
            passed += 1

    print(f"\n总计: {passed}/{len(results)} 项测试通过")

    if passed == len(results):
        print("\n[恭喜] 所有测试通过！")
    else:
        print(f"\n[注意] 有 {len(results) - passed} 项测试失败")

if __name__ == "__main__":
    main()