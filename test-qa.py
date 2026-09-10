#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""RAG 问答功能端到端测试"""
import requests
import json

BASE = "http://localhost:8000"


def get_token():
    r = requests.post(f"{BASE}/api/auth/login",
                      json={"username": "admin", "password": "123456"}, timeout=10)
    r.raise_for_status()
    return r.json()["access_token"]


def main():
    print("=" * 60)
    print("[Test] RAG Q&A end-to-end")
    print("=" * 60)

    token = get_token()
    h = {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}
    print("[OK] Login token acquired")

    # 创建会话
    r = requests.post(f"{BASE}/api/chat/conversations", headers=h, timeout=10)
    r.raise_for_status()
    conv_id = r.json()["id"]
    print(f"[OK] Conversation created: id={conv_id}")

    # 发送问题 - 流式
    print("\n[Test] Send question: '有哪些商品？'")
    payload = {"conversation_id": conv_id, "query": "有哪些商品？"}
    with requests.post(f"{BASE}/api/chat/send", headers=h, json=payload,
                       stream=True, timeout=60) as r:
        print(f"  HTTP {r.status_code}")
        full = ""
        sources = None
        for line in r.iter_lines(decode_unicode=True):
            if not line or not line.startswith("data: "):
                continue
            data = json.loads(line[6:])
            if data.get("type") == "chunk":
                full += data["content"]
                # 打印前几个 chunk 预览
                if len(full) < 120:
                    print(f"  > {data['content']}", end="")
            elif data.get("type") == "done":
                sources = data.get("sources")
        print("\n[OK] Answer received, length=" + str(len(full)))
        print("-" * 40)
        print("Answer preview:")
        print("  " + full[:400])
        print("-" * 40)
        print(f"Sources: {len(sources) if sources else 0}")
        for s in (sources or []):
            print(f"  - {s.get('doc_name')} | score={s.get('score')}")


if __name__ == "__main__":
    main()