"""Cross-Encoder 精排测试。

全部用假模型，不加载真模型——单元测试要能在没有 GPU、
没有下载过模型、甚至没有网络的环境里秒级跑完。

这里最要紧的不是"重排得准不准"（那是 eval 黄金集的事），
而是**精排挂了以后系统还能不能正常工作**。
精排是锦上添花，不能变成新的故障点。
"""
import pytest

from app.services import rag_service, rerank_service
from app.services.rerank_service import rerank


def _cands(n: int) -> list[dict]:
    return [
        {"chunk_id": f"c{i}", "text": f"第 {i} 段内容", "rrf": 1.0 / (i + 1)}
        for i in range(n)
    ]


class _FakeModel:
    """默认把原始顺序**倒过来**打分，便于断言"顺序确实变了"。"""

    def __init__(self, scores=None, error=None):
        self.scores = scores
        self.error = error
        self.seen = []

    def predict(self, pairs, batch_size=16):
        self.seen = pairs
        if self.error:
            raise self.error
        if self.scores is not None:
            return self.scores
        # 越靠后的候选打分越高 → 结果顺序与传入顺序完全相反
        return [float(i) for i in range(len(pairs))]


@pytest.fixture
def rerank_on(monkeypatch):
    monkeypatch.setattr(rerank_service, "RERANK_ENABLED", True)


class TestSkipConditions:
    def test_disabled_returns_input_untouched(self, monkeypatch):
        monkeypatch.setattr(rerank_service, "RERANK_ENABLED", False)
        cands = _cands(10)
        out, detail = rerank("问题", cands, top_k=3)

        assert out is cands, "关闭时应当原样返回，不做任何复制或排序"
        assert detail is None

    def test_skipped_when_candidates_fit_in_top_k(self, rerank_on, monkeypatch):
        """候选数不超过 top_k 时精排毫无意义——它只能重排，不能召回新内容。"""
        monkeypatch.setattr(rerank_service, "get_reranker", lambda: _FakeModel())
        out, detail = rerank("问题", _cands(3), top_k=5)

        assert detail is None
        assert len(out) == 3

    def test_skipped_on_empty_query(self, rerank_on, monkeypatch):
        monkeypatch.setattr(rerank_service, "get_reranker", lambda: _FakeModel())
        _, detail = rerank("   ", _cands(10), top_k=3)
        assert detail is None

    def test_skipped_when_model_unavailable(self, rerank_on, monkeypatch):
        """模型加载失败（没下载、显存不足）时静默跳过，而不是报错。"""
        monkeypatch.setattr(rerank_service, "get_reranker", lambda: None)
        cands = _cands(10)
        out, detail = rerank("问题", cands, top_k=3)

        assert detail is None
        assert out is cands


class TestReranking:
    def test_reorders_and_truncates(self, rerank_on, monkeypatch):
        model = _FakeModel()
        monkeypatch.setattr(rerank_service, "get_reranker", lambda: model)

        out, detail = rerank("问题", _cands(10), top_k=3)

        assert len(out) == 3
        assert detail["input_count"] == 10
        assert detail["output_count"] == 3
        assert detail["reordered"] > 0, "假模型一定会改变顺序，reordered 不该为 0"

    def test_scores_are_attached_to_candidates(self, rerank_on, monkeypatch):
        monkeypatch.setattr(rerank_service, "get_reranker", lambda: _FakeModel())
        out, _ = rerank("问题", _cands(10), top_k=3)
        assert all("rerank_score" in c for c in out)

    def test_higher_score_ranks_first(self, rerank_on, monkeypatch):
        # 给第 0、1、2 条分别打 0.1 / 0.9 / 0.5，期望顺序为 1 → 2 → 0
        scores = [0.1, 0.9, 0.5] + [0.0] * 7
        monkeypatch.setattr(
            rerank_service, "get_reranker", lambda: _FakeModel(scores=scores)
        )

        out, _ = rerank("问题", _cands(10), top_k=3)
        assert [c["chunk_id"] for c in out] == ["c1", "c2", "c0"]

    def test_query_and_text_are_paired_correctly(self, rerank_on, monkeypatch):
        """Cross-Encoder 吃的是 (query, 文档) 配对，配错了分数就毫无意义。"""
        model = _FakeModel()
        monkeypatch.setattr(rerank_service, "get_reranker", lambda: model)

        rerank("我的问题", _cands(5), top_k=2)

        assert all(pair[0] == "我的问题" for pair in model.seen)
        assert [pair[1] for pair in model.seen] == [f"第 {i} 段内容" for i in range(5)]

    def test_custom_text_key(self, rerank_on, monkeypatch):
        model = _FakeModel()
        monkeypatch.setattr(rerank_service, "get_reranker", lambda: model)

        cands = [{"chunk_id": f"c{i}", "content": f"正文{i}"} for i in range(5)]
        rerank("问题", cands, top_k=2, text_key="content")
        assert [pair[1] for pair in model.seen] == [f"正文{i}" for i in range(5)]

    def test_missing_text_does_not_crash(self, rerank_on, monkeypatch):
        monkeypatch.setattr(rerank_service, "get_reranker", lambda: _FakeModel())
        cands = [{"chunk_id": f"c{i}"} for i in range(5)]  # 没有 text 字段
        out, _ = rerank("问题", cands, top_k=2)
        assert len(out) == 2


class TestGracefulDegradation:
    def test_inference_error_falls_back_to_original_order(self, rerank_on, monkeypatch):
        """**最关键的一条**：精排抛异常时，必须退回融合排序的结果。

        否则一次模型推理失败就会让整个问答报错——
        一个"锦上添花"的功能不该有能力搞垮主流程。
        """
        monkeypatch.setattr(
            rerank_service,
            "get_reranker",
            lambda: _FakeModel(error=RuntimeError("CUDA out of memory")),
        )
        cands = _cands(10)
        out, detail = rerank("问题", cands, top_k=3)

        assert detail is None
        assert out is cands, "应当原样返回融合排序的结果"

    def test_model_load_failure_is_memoized(self, monkeypatch):
        """加载失败要记住，不然每次检索都要重试一遍、每次都要等超时。"""
        rerank_service.reset_reranker()

        calls = {"n": 0}

        def _boom(*_a, **_kw):
            calls["n"] += 1
            raise OSError("模型文件不存在")

        import sentence_transformers

        monkeypatch.setattr(sentence_transformers, "CrossEncoder", _boom)

        assert rerank_service.get_reranker() is None
        assert rerank_service.get_reranker() is None
        assert rerank_service.get_reranker() is None
        assert calls["n"] == 1, "失败后不应反复重试加载"

        rerank_service.reset_reranker()  # 清理，避免影响其他用例

    def test_reset_allows_reload(self, monkeypatch):
        rerank_service.reset_reranker()
        monkeypatch.setattr(rerank_service, "_load_failed", True)
        assert rerank_service.get_reranker() is None

        rerank_service.reset_reranker()
        assert rerank_service._load_failed is False


class _FakeEmbedder:
    def embed_query(self, _query):
        return [0.1, 0.2, 0.3]


class TestRefusalFilter:
    """用精排分数做拒答判定。

    这是精排**真正有价值的地方**：它在"重排顺序"上没带来提升（实测 MRR 反而略降），
    但在"知识库里到底有没有答案"这件事上，区分度远超向量分数
    （无答案 0.19 vs 有答案 0.87，而向量是 0.53 vs 0.59，几乎重叠）。

    这一组测试守的是**别把正常问题误判成该拒答**——那比不拒答更糟。
    """

    @staticmethod
    def _stub_retrieval(monkeypatch, scores, threshold):
        """把粗排结果和精排打分手动指定，只测"要不要过滤"这一段。"""
        cands = [
            {"chunk_id": f"c{i}", "text": f"片段{i}", "meta": {}, "similarity": 0.6, "rrf": 0.03 - i * 0.01}
            for i in range(len(scores))
        ]
        monkeypatch.setattr(
            rag_service, "_search_one_collection",
            lambda *a, **k: {
                "vector_hits": [], "bm25_hits": [], "dedup_removed": 0,
                "fused": [dict(c) for c in cands],
            },
        )
        monkeypatch.setattr(rag_service, "get_collection", lambda _n: object())
        monkeypatch.setattr(rag_service, "get_embedding_model", lambda: _FakeEmbedder())
        monkeypatch.setattr(rag_service, "RERANK_REFUSAL_THRESHOLD", threshold)
        monkeypatch.setattr(
            rag_service, "rerank",
            lambda q, c, k: (
                [dict(x, rerank_score=s) for x, s in zip(c, scores)],
                {"model": "fake", "input_count": len(c), "output_count": len(c),
                 "reordered": 0, "top_scores": list(scores)},
            ),
        )

    def test_low_scoring_candidates_are_dropped(self, monkeypatch):
        self._stub_retrieval(monkeypatch, scores=[0.9, 0.05, 0.5, 0.01], threshold=0.35)
        res = rag_service.retrieve("问题", top_k=5, collection_names=["c1"])

        assert res["trace"]["final_count"] == 2
        assert res["trace"]["rerank"]["refusal_filtered"] == 2

    def test_all_low_scores_yield_nothing(self, monkeypatch):
        """全部不对口时必须返回空——上层据此走"知识库中未收录"的拒答路径，
        而不是把一堆无关内容塞给模型自由发挥。"""
        self._stub_retrieval(monkeypatch, scores=[0.02, 0.05], threshold=0.35)
        res = rag_service.retrieve("问题", top_k=5, collection_names=["c1"])

        assert res["documents"] == [[]]
        assert res["trace"]["final_count"] == 0

    def test_high_scores_are_left_alone(self, monkeypatch):
        """正常问题不能被误伤——这是这个功能最需要防的错误。"""
        self._stub_retrieval(monkeypatch, scores=[0.95, 0.88, 0.72], threshold=0.35)
        res = rag_service.retrieve("问题", top_k=5, collection_names=["c1"])

        assert res["trace"]["final_count"] == 3
        assert res["trace"]["rerank"]["refusal_filtered"] == 0

    def test_threshold_zero_disables_filtering(self, monkeypatch):
        self._stub_retrieval(monkeypatch, scores=[0.01, 0.02], threshold=0)
        res = rag_service.retrieve("问题", top_k=5, collection_names=["c1"])

        assert res["trace"]["final_count"] == 2
        assert "refusal_filtered" not in res["trace"]["rerank"]
