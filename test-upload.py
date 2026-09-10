#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import requests
import json

def get_token():
    """获取登录token"""
    url = "http://localhost:8000/api/auth/login"
    data = {
        "username": "admin",
        "password": "123456"
    }
    response = requests.post(url, json=data)
    if response.status_code == 200:
        return response.json().get("access_token")
    else:
        print(f"登录失败: {response.status_code}")
        return None

def upload_document(token):
    """上传文档"""
    url = "http://localhost:8000/api/knowledge/upload"
    headers = {
        "Authorization": f"Bearer {token}"
    }

    # 读取文件
    with open("backend/uploads/test_products.md", "rb") as f:
        files = {"file": f}
        response = requests.post(url, headers=headers, files=files)

    print(f"上传响应: {response.status_code}")
    print(response.text)

def test_rag_query(token):
    """测试RAG查询"""
    url = "http://localhost:8000/api/chat/send"
    headers = {
        "Authorization": f"Bearer {token}"
    }
    data = {
        "query": "有什么商品？"
    }

    response = requests.post(url, headers=headers, json=data)
    print(f"RAG查询响应: {response.status_code}")
    print(response.text[:500] + "..." if len(response.text) > 500 else response.text)

def main():
    print("测试文档上传和RAG查询...")

    # 获取token
    token = get_token()
    if not token:
        print("无法获取token")
        return

    print("获取token成功")

    # 上传文档
    print("\n上传文档...")
    upload_document(token)

    # 等待文档处理
    print("\n等待文档处理...")
    import time
    time.sleep(5)

    # 测试RAG查询
    print("\n测试RAG查询...")
    test_rag_query(token)

if __name__ == "__main__":
    main()