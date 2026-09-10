# -*- coding: utf-8 -*-
"""把 qa_results.json 渲染成可读的演示问答记录（Markdown）"""
import json
import os

HERE = os.path.dirname(os.path.abspath(__file__))
results = json.load(open(os.path.join(HERE, "qa_results.json"), encoding="utf-8"))

LINES = []
w = LINES.append

w("# CloudFlow 技术支持场景 — RAG 问答演示记录")
w("")
w("> 本记录由脚本真实调用系统接口生成，非人工撰写。")
w("> 场景：B2B SaaS 产品「CloudFlow 智能数据集成平台」的技术支持知识库。")
w("> 检索范围：已限定到「CloudFlow 产品知识库」（多知识库隔离）。")
w("")
w("## 演示摘要")
w("")
w("| # | 考察点 | 引用数 | 无来源污染 | 耗时 |")
w("|---|--------|--------|-----------|------|")
for i, r in enumerate(results, 1):
    srcs = r.get("sources", [])
    mao = sum(1 for s in srcs if "毛泽东" in s["doc_name"])
    w(f"| {i} | {r['category']} | {len(srcs)} | {'是' if mao == 0 else f'否({mao})'} | {r.get('elapsed_sec')}s |")
w("")

total_src = sum(len(r.get("sources", [])) for r in results)
mao_src = sum(sum(1 for s in r.get("sources", []) if "毛泽东" in s["doc_name"]) for r in results)
w(f"**汇总**：共 {len(results)} 组问答，{total_src} 条引用，其中无关语料污染 **{mao_src}** 条。")
w("")
w("---")
w("")

for i, r in enumerate(results, 1):
    w(f"## {i}. {r['category']}")
    w("")
    if r.get("note"):
        w(f"> **{r['note']}**")
        w("")
    w(f"**提问**：{r['query']}")
    w("")
    w("**回答**：")
    w("")
    ans = r.get("answer", "").strip()
    for line in ans.splitlines():
        w(f"> {line}" if line.strip() else ">")
    w("")
    srcs = r.get("sources", [])
    w(f"**引用来源**（{len(srcs)} 条）：")
    w("")
    w("| 相似度 | 文档 |")
    w("|--------|------|")
    for s in srcs:
        fn = s["doc_name"]
        if len(fn) > 33 and fn[32] == "_":
            fn = fn[33:]
        w(f"| {s['score']} | {fn} |")
    w("")
    w(f"*耗时 {r.get('elapsed_sec')}s*")
    w("")
    w("---")
    w("")

out = os.path.join(HERE, "演示问答记录.md")
with open(out, "w", encoding="utf-8") as f:
    f.write("\n".join(LINES))
print("已生成:", out)
print(f"共 {len(results)} 组问答, {total_src} 条引用, 污染 {mao_src} 条")
