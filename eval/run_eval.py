# -*- coding: utf-8 -*-
"""
RAG 检索质量评估脚本。

回答一个核心问题：**改动检索策略后，到底变好了还是变坏了？**

指标定义：
- Hit@K  : 期望文档是否出现在 Top-K 中（只要命中一个就算）
- Recall@K: 期望文档被召回的比例（多文档问题才有区分度）
- MRR@K  : 第一个命中文档的排名倒数，越接近 1 说明正确文档排得越靠前
- 拒答正确率: 知识库无答案时，最高相似度是否低于阈值（即不应给出引用）

用法：
    python run_eval.py                  # 依次跑三档并对比（默认）
    python run_eval.py --config hybrid
    python run_eval.py --config rerank

三档是递进的：向量 → 加 BM25 → 加精排。
只看最终结果说明不了什么，**看每一档各贡献了多少**才是重点——
如果某一档没有提升，就应该把它关掉，而不是因为"听起来更高级"就留着。
"""
import argparse
import json
import os
import re
import sys
import time

# 中文 Windows 上，输出被重定向到文件或管道时，Python 会退回用系统 ANSI 编码
# （GBK）来写，遇到 ✓ / ✗ 这类符号直接抛 UnicodeEncodeError，
# **整个评估脚本崩掉**——而控制台里直接跑却完全正常，属于只在特定调用方式下
# 才暴露的问题（`python run_eval.py > result.txt` 就会踩到）。
# 显式指定 UTF-8，让输出与调用方式无关。
for _stream in (sys.stdout, sys.stderr):
    if hasattr(_stream, "reconfigure"):
        _stream.reconfigure(encoding="utf-8", errors="replace")

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "backend"))
os.environ.setdefault("HF_HOME", "D:/mydo/huggingface_cache")

from app.config import RELEVANCE_THRESHOLD, RETRIEVAL_TOP_K
from app.services import rag_service, rerank_service
from app.utils.cache import clear_cache

HERE = os.path.dirname(os.path.abspath(__file__))
PREFIX_RE = re.compile(r"^[0-9a-f]{32}_")


def clean_doc_name(name: str) -> str:
    """去掉上传时加在文件名前的 uuid 前缀"""
    return PREFIX_RE.sub("", name or "")


def load_golden_set() -> list[dict]:
    with open(os.path.join(HERE, "golden_set.json"), encoding="utf-8") as f:
        return json.load(f)["cases"]


def retrieve_docs(query: str, collections: list[str], top_k: int) -> tuple[list[str], list[float]]:
    """返回 (按相关性排序的文档名列表, 对应的相似度列表)"""
    results = rag_service.retrieve(query, top_k, collections)
    metas = results.get("metadatas", [[]])[0]
    dists = results.get("distances", [[]])[0]
    docs = [clean_doc_name(m.get("doc_name", "")) for m in metas]
    sims = [round(1.0 - d, 4) for d in dists]
    return docs, sims


def evaluate(label: str, collections: list[str], top_k: int) -> dict:
    cases = load_golden_set()
    rows = []

    for c in cases:
        t0 = time.time()
        docs, sims = retrieve_docs(c["query"], collections, top_k)
        latency = (time.time() - t0) * 1000

        expected = set(c["expected_docs"])
        if c["type"] == "refusal":
            # 拒答场景：最高相似度低于阈值 → 正确（不会给出无来源的回答）
            max_sim = max(sims) if sims else 0.0
            rows.append({
                "id": c["id"], "type": c["type"],
                "hit": max_sim < RELEVANCE_THRESHOLD,
                "recall": 1.0 if max_sim < RELEVANCE_THRESHOLD else 0.0,
                "rr": 1.0 if max_sim < RELEVANCE_THRESHOLD else 0.0,
                "max_sim": max_sim, "latency_ms": latency,
            })
            continue

        hit = any(d in expected for d in docs)
        inter = len(expected & set(docs))
        recall = inter / len(expected) if expected else 0.0
        rr = 0.0
        for rank, d in enumerate(docs, 1):
            if d in expected:
                rr = 1.0 / rank
                break
        rows.append({
            "id": c["id"], "type": c["type"],
            "hit": hit, "recall": recall, "rr": rr,
            "docs": docs[:top_k], "latency_ms": latency,
        })

    n = len(rows)
    hit_rate = sum(1 for r in rows if r["hit"]) / n
    mean_recall = sum(r["recall"] for r in rows) / n
    mrr = sum(r["rr"] for r in rows) / n
    avg_latency = sum(r["latency_ms"] for r in rows) / n

    by_type: dict[str, list] = {}
    for r in rows:
        by_type.setdefault(r["type"], []).append(r)

    return {
        "label": label,
        "n": n,
        "hit_rate": hit_rate,
        "recall": mean_recall,
        "mrr": mrr,
        "avg_latency_ms": avg_latency,
        "by_type": {
            t: {
                "n": len(rs),
                "hit_rate": sum(1 for r in rs if r["hit"]) / len(rs),
                "recall": sum(r["recall"] for r in rs) / len(rs),
                "mrr": sum(r["rr"] for r in rs) / len(rs),
            }
            for t, rs in by_type.items()
        },
        "rows": rows,
    }


def print_result(res: dict):
    print(f"\n{'='*76}")
    print(f"配置: {res['label']}")
    print(f"{'='*76}")
    print(f"  样本数: {res['n']}    Hit@{RETRIEVAL_TOP_K}: {res['hit_rate']:.1%}    "
          f"Recall@{RETRIEVAL_TOP_K}: {res['recall']:.1%}    MRR: {res['mrr']:.3f}    "
          f"平均检索耗时: {res['avg_latency_ms']:.0f}ms")
    print()
    print(f"  {'问题类型':<12}{'样本':<6}{'Hit率':<10}{'Recall':<10}{'MRR'}")
    print(f"  {'-'*50}")
    for t, m in sorted(res["by_type"].items()):
        print(f"  {t:<12}{m['n']:<6}{m['hit_rate']:<10.1%}{m['recall']:<10.1%}{m['mrr']:.3f}")

    misses = [r for r in res["rows"] if not r["hit"]]
    if misses:
        print(f"\n  未命中样本 ({len(misses)} 条):")
        for r in misses:
            extra = f" max_sim={r.get('max_sim')}" if r["type"] == "refusal" else f" 实际召回={r.get('docs', [])[:3]}"
            print(f"    ✗ {r['id']} [{r['type']}]{extra}")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument(
        "--config",
        choices=["both", "vector", "hybrid", "rerank"],
        default="both",
        help="both=跑全部三档并对比（默认）；其余为只跑单一配置",
    )
    ap.add_argument("--kb-id", type=int, default=2, help="要评估的知识库 ID")
    args = ap.parse_args()

    from app.database import SessionLocal
    from app.models.knowledge_base import KnowledgeBase

    db = SessionLocal()
    kb = db.query(KnowledgeBase).filter(KnowledgeBase.id == args.kb_id).first()
    if not kb:
        print(f"知识库不存在: id={args.kb_id}")
        return
    collections = [kb.collection_name]
    print(f"评估知识库: {kb.name} (collection={kb.collection_name})")
    db.close()

    # (标签, 混合检索, 去冗余, 精排)
    # 默认跑三档，因为检索优化是**递进**的：
    #   向量 → 加 BM25 补精确匹配 → 加精排重排顺序
    # 分档跑才能看出每一层各自贡献了多少，而不是只有一个笼统的"变好了"。
    all_configs = [
        ("向量检索（基线）", False, False, False),
        ("混合检索 + 去冗余", True, True, False),
        ("混合检索 + 去冗余 + 精排", True, True, True),
    ]
    configs = {
        "both": all_configs,
        "vector": [all_configs[0]],
        "hybrid": [all_configs[1]],
        "rerank": [all_configs[2]],
    }[args.config]

    results = []
    for label, hybrid, dedup, use_rerank in configs:
        # 运行时切换检索配置（重新加载配置需重启，这里直接改模块变量）
        rag_service.HYBRID_SEARCH_ENABLED = hybrid
        rag_service.DEDUP_ENABLED = dedup
        # 注意：rag_service 是 `from ... import rerank` 导入的函数对象，
        # 但该函数在**自己的模块**里读取 RERANK_ENABLED，所以改这里的值对它生效
        rerank_service.RERANK_ENABLED = use_rerank
        clear_cache()          # 清空检索缓存与 BM25 索引，确保各配置互不污染
        rag_service.clear_bm25_cache()

        res = evaluate(label, collections, RETRIEVAL_TOP_K)
        results.append(res)
        print_result(res)

    if len(results) > 1:
        a, b = results[0], results[-1]
        print(f"\n{'='*76}")
        print(f"对比结论：{a['label']} → {b['label']}")
        print(f"{'='*76}")
        print(f"  Hit@{RETRIEVAL_TOP_K}  : {a['hit_rate']:.1%} → {b['hit_rate']:.1%}  "
              f"({(b['hit_rate']-a['hit_rate'])*100:+.1f} 个百分点)")
        print(f"  Recall@{RETRIEVAL_TOP_K}: {a['recall']:.1%} → {b['recall']:.1%}  "
              f"({(b['recall']-a['recall'])*100:+.1f} 个百分点)")
        print(f"  MRR     : {a['mrr']:.3f} → {b['mrr']:.3f}  ({b['mrr']-a['mrr']:+.3f})")
        print(f"  延迟    : {a['avg_latency_ms']:.0f}ms → {b['avg_latency_ms']:.0f}ms  "
              f"({b['avg_latency_ms']-a['avg_latency_ms']:+.0f}ms)")

        # 精排的收益主要体现在 MRR（把正确答案排到更前面），
        # 而不是 Hit@K（有没有召回）。看起来"提升不明显"时先看 MRR。
        if len(results) == 3:
            m = results[1]
            print("\n  其中「混合检索 → 加精排」这一段：")
            print(f"    Hit@{RETRIEVAL_TOP_K}: {m['hit_rate']:.1%} → {b['hit_rate']:.1%}  "
                  f"({(b['hit_rate']-m['hit_rate'])*100:+.1f} 个百分点)")
            print(f"    MRR    : {m['mrr']:.3f} → {b['mrr']:.3f}  ({b['mrr']-m['mrr']:+.3f})")
            print(f"    延迟   : {m['avg_latency_ms']:.0f}ms → {b['avg_latency_ms']:.0f}ms  "
                  f"({b['avg_latency_ms']-m['avg_latency_ms']:+.0f}ms)  ← 精排的代价在这里")

    out = os.path.join(HERE, "eval_result.json")
    with open(out, "w", encoding="utf-8") as f:
        json.dump([{k: v for k, v in r.items()} for r in results], f, ensure_ascii=False, indent=2)
    print(f"\n结果已保存: {out}")


if __name__ == "__main__":
    main()
