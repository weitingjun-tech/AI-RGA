#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
RAG system basic functionality test (ASCII-only output)
"""

import sys
import time
import requests
import json
from pathlib import Path

sys.path.append(str(Path(__file__).parent / "backend"))

# Use ASCII markers only to avoid GBK encoding issues on Windows
OK = "[OK]"
FAIL = "[FAIL]"

def test_ollama_connection():
    print("\n[Test 1] Ollama service...")
    try:
        response = requests.get("http://localhost:11434/api/tags", timeout=10)
        if response.status_code == 200:
            models = response.json().get("models", [])
            print(OK + " Ollama running")
            print("   Models: " + ", ".join([m["name"] for m in models]))
            return True
        else:
            print(FAIL + " Ollama returned " + str(response.status_code))
            return False
    except Exception as e:
        print(FAIL + " Ollama unreachable: " + str(e)[:120])
        return False

def test_fastapi_health():
    print("\n[Test 2] FastAPI health...")
    try:
        response = requests.get("http://localhost:8000/api/health", timeout=10)
        if response.status_code == 200:
            data = response.json()
            print(OK + " FastAPI running: " + data.get("service", ""))
            return True
        else:
            print(FAIL + " FastAPI returned " + str(response.status_code))
            return False
    except Exception as e:
        print(FAIL + " FastAPI unreachable: " + str(e)[:120])
        return False

def test_login():
    print("\n[Test 3] User login...")
    try:
        url = "http://localhost:8000/api/auth/login"
        data = {"username": "admin", "password": "123456"}
        response = requests.post(url, json=data, timeout=10)
        if response.status_code == 200:
            result = response.json()
            username = result.get("username", "")
            token = result.get("access_token", "")
            print(OK + " Login success. User: " + username)
            return token
        else:
            print(FAIL + " Login returned " + str(response.status_code) + ": " + response.text[:200])
            return None
    except Exception as e:
        print(FAIL + " Login error: " + str(e)[:120])
        return None

def test_chat_conversations(token):
    print("\n[Test 4] Create conversation...")
    if not token:
        print("   Skipped (no token)")
        return False
    try:
        url = "http://localhost:8000/api/chat/conversations"
        headers = {"Authorization": "Bearer " + token}
        response = requests.post(url, headers=headers, timeout=10)
        if response.status_code == 200:
            conv = response.json()
            print(OK + " Conversation created. ID=" + str(conv.get("id")))
            return conv.get("id")
        else:
            print(FAIL + " Create returned " + str(response.status_code) + ": " + response.text[:200])
            return False
    except Exception as e:
        print(FAIL + " Create error: " + str(e)[:120])
        return False

def test_knowledge_documents(token):
    print("\n[Test 5] Get document list...")
    if not token:
        print("   Skipped (no token)")
        return False
    try:
        url = "http://localhost:8000/api/knowledge/documents"
        headers = {"Authorization": "Bearer " + token}
        response = requests.get(url, headers=headers, timeout=10)
        if response.status_code == 200:
            data = response.json()
            docs = data.get("documents", [])
            total = data.get("total", 0)
            print(OK + " Documents: " + str(total) + " total")
            for doc in docs[:3]:
                print("   - " + (doc.get("filename") or "") + " [" + (doc.get("status") or "") + "]")
            return True
        else:
            print(FAIL + " Get docs returned " + str(response.status_code) + ": " + response.text[:200])
            return False
    except Exception as e:
        print(FAIL + " Get docs error: " + str(e)[:120])
        return False

def test_rag_upload(token):
    print("\n[Test 6] Upload document...")
    if not token:
        print("   Skipped (no token)")
        return False
    try:
        url = "http://localhost:8000/api/knowledge/upload"
        headers = {"Authorization": "Bearer " + token}
        test_file = "d:/mydo/backend/uploads/test_products.md"
        with open(test_file, "rb") as f:
            response = requests.post(url, headers=headers, files={"file": f}, timeout=30)
        if response.status_code == 200:
            data = response.json()
            print(OK + " Uploaded: " + str(data.get("filename", "")))
            print("   Doc ID=" + str(data.get("document_id", "")))
            return data.get("document_id")
        else:
            print(FAIL + " Upload returned " + str(response.status_code) + ": " + response.text[:200])
            return False
    except Exception as e:
        print(FAIL + " Upload error: " + str(e)[:120])
        return False

def main():
    print("=" * 60)
    print("RAG Knowledge QA System - Basic Function Test")
    print("=" * 60)

    results = []
    results.append(("Ollama", test_ollama_connection()))
    results.append(("FastAPI", test_fastapi_health()))

    token = test_login()
    results.append(("Login", token is not None))

    conv_id = test_chat_conversations(token)
    results.append(("Conversation", conv_id is not False))

    results.append(("Documents", test_knowledge_documents(token)))

    doc_id = test_rag_upload(token)
    results.append(("Upload", doc_id is not False))

    print("\n" + "=" * 60)
    print("Test Summary:")
    print("=" * 60)

    passed = 0
    for name, result in results:
        status = "[PASS]" if result else "[FAIL]"
        print(status + " " + name)
        if result:
            passed += 1

    print("\nTotal: " + str(passed) + "/" + str(len(results)) + " passed")
    print("=" * 60)

    if passed == len(results):
        print("\n[SUCCESS] All core functions working!")
        print("\nAccess:")
        print("  Frontend : http://localhost:5173")
        print("  Backend  : http://localhost:8000")
        print("  API Docs : http://localhost:8000/docs")
        print("\nAccounts: admin / 123456")
    else:
        print("\n[WARN] " + str(len(results) - passed) + " test(s) failed.")

if __name__ == "__main__":
    main()