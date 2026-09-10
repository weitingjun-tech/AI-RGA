# -*- coding: utf-8 -*-
"""
CloudFlow 技术支持场景 — RAG 真实问答演示脚本
通过真实调用后端 /api/chat/send 接口执行提问，记录完整回答与引用来源。
"""
import json
import os
import sys
import time
import urllib.request

BASE = "http://localhost:8000"
OUT_DIR = os.path.dirname(os.path.abspath(__file__))

# 检索范围：CloudFlow 产品知识库的 ID（多知识库隔离，避免无关语料干扰）
# 可通过环境变量 KB_ID 覆盖；为空表示检索全部知识库
KB_IDS = [int(x) for x in os.environ.get("KB_ID", "2").split(",") if x.strip()]

# ==================== 演示问题集 ====================
# 每个问题标注了考察点，便于面试时讲解
QUESTIONS = [
    {
        "id": "q1",
        "category": "故障排查（单文档检索）",
        "note": "考察点：能否从故障手册中定位到正确的错误码并给出结构化排查步骤",
        "query": "我的同步任务一直报 CONN_TIMEOUT，应该怎么排查？",
    },
    {
        "id": "q2",
        "category": "计费政策（数值准确性）",
        "note": "考察点：能否准确引用套餐额度与超额单价，不编造数字",
        "query": "专业版每个月包含多少同步行数额度？如果超额了怎么收费？",
    },
    {
        "id": "q3",
        "category": "跨文档综合（多跳推理）",
        "note": "考察点：需要同时检索「连接器清单」「套餐说明」「产品概述」三份文档才能完整回答",
        "query": "我要把 MySQL 的数据实时同步到 Snowflake，需要开通什么套餐？怎么配置？",
    },
    {
        "id": "q4",
        "category": "API 文档（结构化信息）",
        "note": "考察点：能否从 API 文档中提取必填字段并组织成可用的调用示例",
        "query": "怎么用 API 创建一个同步任务？哪些字段是必填的？",
    },
    {
        "id": "q5",
        "category": "表格数据（CSV 解析）",
        "note": "考察点：CSV 类表格数据能否被正确检索并回答",
        "query": "你们支持 Kafka 作为数据源吗？支持的话需要什么套餐？",
    },
    {
        "id": "q6",
        "category": "安全合规（DOCX/PDF 内容）",
        "note": "考察点：能否命中 DOCX 与安全白皮书中的内容",
        "query": "我的业务数据会被 CloudFlow 看到吗？你们有哪些合规认证？",
    },
    {
        "id": "q7",
        "category": "边界测试（拒答能力）",
        "note": "考察点：知识库中不存在的信息，模型是否诚实拒答而非编造 —— 幻觉控制能力",
        "query": "你们 CEO 的手机号是多少？公司总部在哪个城市？",
    },
    {
        "id": "q8",
        "category": "版本更新（TXT 日志）",
        "note": "考察点：TXT 格式的更新日志能否被检索",
        "query": "2.4.0 版本更新了哪些内容？",
    },
]


def login() -> str:
    req = urllib.request.Request(
        f"{BASE}/api/auth/login",
        data=json.dumps({"username": "admin", "password": "123456"}).encode(),
        headers={"Content-Type": "application/json"},
    )
    return json.loads(urllib.request.urlopen(req).read())["access_token"]


def ask(token: str, query: str, conversation_id=None):
    """调用 /api/chat/send，解析 SSE 流，返回 (完整回答, sources, conversation_id)"""
    payload = {"query": query, "conversation_id": conversation_id}
    if KB_IDS:
        payload["kb_ids"] = KB_IDS
    body = json.dumps(payload).encode()
    req = urllib.request.Request(
        f"{BASE}/api/chat/send",
        data=body,
        headers={
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
        },
    )
    answer_parts = []
    sources = []
    conv_id = conversation_id

    with urllib.request.urlopen(req, timeout=300) as resp:
        for raw_line in resp:
            line = raw_line.decode("utf-8", errors="replace").strip()
            if not line.startswith("data:"):
                continue
            payload = line[5:].strip()
            if not payload:
                continue
            try:
                evt = json.loads(payload)
            except json.JSONDecodeError:
                continue

            etype = evt.get("type")
            if etype == "chunk":                       # 流式增量内容
                answer_parts.append(evt.get("content", ""))
            elif etype == "done":                      # 结束事件，携带引用来源
                sources = evt.get("sources", [])
                conv_id = evt.get("conversation_id", conv_id)
            elif etype == "error":
                answer_parts.append(f"[服务端错误] {evt.get('message')}")

    return "".join(answer_parts), sources, conv_id


def main():
    token = login()
    results = []

    for i, q in enumerate(QUESTIONS, 1):
        print(f"\n{'='*78}")
        print(f"[{i}/{len(QUESTIONS)}] {q['category']}")
        print(f"问题: {q['query']}")
        print("-" * 78)

        t0 = time.time()
        try:
            answer, sources, conv_id = ask(token, q["query"])
            elapsed = time.time() - t0
        except Exception as e:
            print(f"提问失败: {e}")
            results.append({**q, "error": str(e)})
            continue

        print(f"回答 ({len(answer)} 字, {elapsed:.1f}s):")
        print(answer if answer else "(空回答)")
        print(f"\n引用来源 ({len(sources)} 条):")
        for s in sources:
            fname = s["doc_name"]
            if len(fname) > 33 and fname[32] == "_":
                fname = fname[33:]
            print(f"  · {fname}  score={s['score']}")

        results.append({
            **q,
            "answer": answer,
            "sources": sources,
            "elapsed_sec": round(elapsed, 1),
            "conversation_id": conv_id,
        })

    # 保存原始结果
    out_path = os.path.join(OUT_DIR, "qa_results.json")
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(results, f, ensure_ascii=False, indent=2)
    print(f"\n\n原始结果已保存: {out_path}")


if __name__ == "__main__":
    main()
