"""Cross-Encoder 精排（Reranker）。

**为什么粗排之后还需要精排**
现在的混合检索（向量 + BM25）属于"粗排"：
- 向量检索把 query 和文档**分别**编码成向量再算距离，两者从未"见过面"，
  交互信息只能靠一个固定维度的向量表达，精度天然有上限
- BM25 只看词是否出现，完全不理解语义

Cross-Encoder 把 (query, 文档) **拼在一起**送进模型，
让两者在每一层注意力里充分交互，因此打分准得多。
代价是没法预计算——每个候选都要现场跑一遍模型，
所以只能用来重排少量候选，不能拿来检索全库。

标准做法就是：**粗排召回一批（快而全）→ 精排挑出最好的几个（慢而准）**。

**降级策略**
模型加载失败或推理异常时，直接返回原顺序，绝不抛异常。
精排是"好上加好"，不是必需环节——它挂了顶多效果退回改造前，
而不是整个问答不可用。
"""
import logging
import threading
from typing import Optional

from app.config import RERANK_ENABLED, RERANK_MODEL

logger = logging.getLogger("rag-app")

_model = None
_model_lock = threading.Lock()
_load_failed = False


def get_reranker():
    """懒加载 Cross-Encoder 模型。

    不在模块导入时加载：模型初始化要几秒，会让应用启动变慢；
    而且如果它加载失败，也不该影响那些根本用不到精排的接口。

    加载失败后会记住失败状态，避免每次检索都重试一遍（那样每次都要等超时）。
    """
    global _model, _load_failed

    if _model is not None or _load_failed:
        return _model

    with _model_lock:
        if _model is not None or _load_failed:
            return _model
        try:
            from sentence_transformers import CrossEncoder

            logger.info(f"加载精排模型: {RERANK_MODEL}（首次较慢）")
            _model = CrossEncoder(RERANK_MODEL, max_length=512)
            logger.info(f"精排模型加载完成: {RERANK_MODEL}")
        except Exception as exc:
            _load_failed = True
            logger.error(
                f"精排模型加载失败（{RERANK_MODEL}）：{exc}。"
                "本次及后续检索将跳过精排，直接使用融合排序。"
            )
    return _model


def reset_reranker() -> None:
    """清空模型缓存。测试用，也让"重新加载"成为可能（比如换模型后）。"""
    global _model, _load_failed
    with _model_lock:
        _model = None
        _load_failed = False


def rerank(
    query: str,
    candidates: list[dict],
    top_k: int,
    text_key: str = "text",
) -> tuple[list[dict], Optional[dict]]:
    """用 Cross-Encoder 对候选重新排序，返回前 top_k 个。

    Args:
        candidates: 融合后的候选列表，每项需包含 `text_key` 指定的正文字段
        top_k: 精排后保留的数量

    Returns:
        (重排后的候选, 精排明细)。明细会写进检索日志，
        便于事后回答「这次精排到底动了哪些结果」。
        跳过精排时明细为 None。
    """
    if not RERANK_ENABLED:
        return candidates, None
    # 候选本来就不多时精排没有意义——它只能重排，不能召回新内容
    if len(candidates) <= top_k:
        return candidates, None
    if not query or not query.strip():
        return candidates, None

    before_order = [c.get("chunk_id") for c in candidates]

    try:
        model = get_reranker()
        if model is None:
            return candidates, None

        pairs = [(query, c.get(text_key, "") or "") for c in candidates]
        scores = model.predict(pairs, batch_size=16)

        for cand, score in zip(candidates, scores):
            cand["rerank_score"] = float(score)

        ranked = sorted(candidates, key=lambda c: -c.get("rerank_score", 0.0))
        selected = ranked[:top_k]

        detail = {
            "model": RERANK_MODEL,
            "input_count": len(candidates),
            "output_count": len(selected),
            # 记录"排序发生了变化"的条数，这是判断精排是否真的生效的直接指标。
            # 全为 0 说明精排没起作用（或模型对这批数据没有区分度）。
            "reordered": sum(
                1
                for i, c in enumerate(selected)
                if i < len(before_order) and before_order[i] != c.get("chunk_id")
            ),
            "top_scores": [
                round(c.get("rerank_score", 0.0), 4) for c in selected[:5]
            ],
        }
        return selected, detail

    except Exception as exc:
        # 精排失败不能影响检索：退回融合排序的结果
        logger.warning(f"精排失败，使用融合排序结果: {exc}")
        return candidates, None
