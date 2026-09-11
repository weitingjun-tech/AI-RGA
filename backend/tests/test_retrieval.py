"""检索核心算法测试：中文分词 / RRF 融合 / 去冗余 / 上下文构建。

这些都是**纯函数**，不碰数据库、不碰模型，因此跑得极快、结果完全确定。
把检索效果交给一个 30 条的黄金集评估，把检索**逻辑正确性**交给这些单元测试——
两者互补：评估回答"效果好不好"，单元测试回答"实现对不对"。
"""
import pytest

from app.services import rag_service
from app.services.rag_service import (
    _dedup_candidates,
    _rrf_fuse,
    build_context_from_results,
    tokenize,
)


class TestTokenize:
    """BM25 分词。中文用二元组而非单字，这是实测调优出来的结论。"""

    @pytest.mark.parametrize(
        "text,expected",
        [
            ("conn_timeout", ["conn_timeout"]),
            ("2.4.0", ["2.4.0"]),
            ("task_7f3c91a2", ["task_7f3c91a2"]),
            ("ERR-5001", ["err-5001"]),
        ],
    )
    def test_technical_tokens_stay_whole(self, text, expected):
        """型号、错误码、下划线标识必须整体保留。

        这是混合检索补足向量短板的关键：向量对 "ERR-5001" 这类符号几乎无感，
        一旦被拆成 "err" "5001"，BM25 也就失去了精确匹配能力。
        """
        assert tokenize(text) == expected

    def test_chinese_uses_bigrams(self):
        assert tokenize("你好世界") == ["你好", "好世", "世界"]

    def test_single_chinese_char_is_kept(self):
        assert tokenize("好") == ["好"]

    def test_chinese_and_ascii_mixed(self):
        tokens = tokenize("错误码 ERR-5001 怎么解决")
        assert "错误" in tokens and "误码" in tokens
        assert "err-5001" in tokens
        assert "怎么" in tokens

    def test_lowercased(self):
        assert tokenize("ABC") == ["abc"]

    def test_empty_and_none(self):
        assert tokenize("") == []
        assert tokenize(None) == []

    def test_punctuation_is_not_a_token(self):
        """标点不该进索引，否则 "，" 会成为命中一切的高频噪声。"""
        for token in tokenize("你好，世界！"):
            assert token.strip("，！") == token


class TestRrfFuse:
    """倒数排序融合。

    核心价值：只用**排名**、不用分数，因此可以直接融合量纲完全不同的
    向量相似度（0~1）和 BM25 分值（0~30+），不需要调权重。
    """

    def test_only_ranks_matter_not_scores(self):
        """两路各自排第一的两个不同文档，融合分数应当相等。

        证明融合函数没有暗含"某一路更重要"。
        """
        fused = _rrf_fuse([["a"], ["b"]])
        assert fused["a"] == pytest.approx(fused["b"])

    def test_consensus_beats_single_list_top(self):
        """两路都认的文档，应当胜过只有一路排第一的文档。

        这正是融合的意义：单路的第一名可能是噪声，两路都认可的才可信。
        """
        fused = _rrf_fuse([["a", "b"], ["c", "b"]])
        assert fused["b"] > fused["a"], "两路都排第 2 应当胜过只在一路排第 1"

    def test_extreme_ranks_beat_middle_ranks_by_a_hair(self):
        """1/(k+r) 是**凸函数**，所以「第 1 + 第 3」会以极小差距胜过「第 2 + 第 2」。

        实测：1/61 + 1/63 = 0.0322664 > 2/62 = 0.0322581，差 8.4e-06。
        这不是 bug，是 RRF 的固有性质——但当 k 很小或排名差距很大时会放大，
        调参时不应当作"两路都命中必然更优"来推理。
        """
        fused = _rrf_fuse([["a", "b", "c"], ["c", "b", "a"]])
        assert fused["a"] == pytest.approx(fused["c"])
        assert fused["a"] > fused["b"]
        assert fused["a"] - fused["b"] < 1e-5, "差距应当极其微小"

    def test_document_in_both_lists_accumulates(self):
        fused = _rrf_fuse([["a"], ["a"]])
        assert fused["a"] == pytest.approx(2 / 61)

    def test_empty_input(self):
        assert _rrf_fuse([]) == {}
        assert _rrf_fuse([[]]) == {}

    def test_k_is_configurable(self):
        """k 越小，排名靠前的优势越明显。"""
        small_k = _rrf_fuse([["a", "b"]], k=1)
        large_k = _rrf_fuse([["a", "b"]], k=1000)
        assert (small_k["a"] - small_k["b"]) > (large_k["a"] - large_k["b"])


class TestDedup:
    """去冗余：重复片段会挤占 Top-K 名额，让有信息量的片段进不了上下文。"""

    def test_near_duplicate_is_removed(self):
        a = {"tokens": ["安装", "步骤", "第一", "步", "打开"]}
        b = {"tokens": ["安装", "步骤", "第一", "步", "点击"]}  # 4/6 重叠
        kept, removed = _dedup_candidates([a, b], threshold=0.6)
        assert removed == 1
        assert len(kept) == 1

    def test_distinct_passages_are_kept(self):
        a = {"tokens": ["安装", "步骤"]}
        b = {"tokens": ["计费", "规则"]}
        kept, removed = _dedup_candidates([a, b], threshold=0.8)
        assert removed == 0
        assert len(kept) == 2

    def test_first_occurrence_wins(self):
        """保留先出现的那条（此时候选已按 RRF 分数排好序）。"""
        first = {"tokens": ["a", "b", "c"], "id": 1}
        second = {"tokens": ["a", "b", "c"], "id": 2}
        kept, _ = _dedup_candidates([first, second], threshold=0.8)
        assert kept[0]["id"] == 1

    def test_empty_token_candidates_are_kept(self):
        """分不出词的片段不该被当成"重复"而丢掉。"""
        kept, removed = _dedup_candidates([{"tokens": []}, {"tokens": []}], 0.8)
        assert removed == 0
        assert len(kept) == 2

    def test_three_way_chain(self):
        """去重是跟"已保留的"比，不是跟"上一条"比。"""
        a = {"tokens": ["a", "b", "c", "d"]}
        b = {"tokens": ["a", "b", "c", "d"]}  # 与 a 重复
        c = {"tokens": ["a", "b", "c", "d"]}  # 与 a 也重复
        kept, removed = _dedup_candidates([a, b, c], threshold=0.8)
        assert (len(kept), removed) == (1, 2)


class TestRetrieveScopeIsolation:
    """检索范围收敛：**空列表必须真的是"什么都不检索"**。

    这与 test_acl.py 是同一个漏洞的两端：ACL 层算出了空集合，
    检索层如果把它当成"那就检索全部"，前面的权限计算就白做了。
    """

    def test_empty_collection_list_short_circuits(self, monkeypatch):
        """传 [] 应当立即返回空结果，且**不加载 embedding 模型**。

        用"模型加载会抛异常"来证明它确实走了短路分支——
        否则这个测试只能证明"返回了空"，而空结果可能来自"查了但没查到"。
        """

        def _explode():
            raise AssertionError("检索范围为空时不应该加载 embedding 模型")

        monkeypatch.setattr(rag_service, "get_embedding_model", _explode)

        result = rag_service.retrieve("任意问题", collection_names=[])
        assert result["documents"] == [[]]
        assert result["trace"]["final_count"] == 0
        assert result["trace"]["collection_names"] == []

    def test_empty_list_does_not_enumerate_all_collections(self, monkeypatch):
        """传 [] 时绝不能去枚举全部知识库——这正是越权漏洞的形态。"""

        def _explode():
            raise AssertionError("检索范围为空时不应该枚举全部 collection")

        monkeypatch.setattr(rag_service, "list_collection_names", _explode)
        monkeypatch.setattr(rag_service, "get_embedding_model", _explode)

        rag_service.retrieve("任意问题", collection_names=[])

    def test_none_still_means_all_collections(self, monkeypatch):
        """None 与 [] 的语义必须保持区分，缺一不可。"""
        monkeypatch.setattr(rag_service, "list_collection_names", lambda: [])
        monkeypatch.setattr(rag_service, "get_embedding_model", lambda: _FakeEmbedder())

        result = rag_service.retrieve("任意问题", collection_names=None)
        assert result["trace"]["collection_names"] == []


class _FakeEmbedder:
    def embed_query(self, _query):
        return [0.1, 0.2, 0.3]


class TestBuildContext:
    def test_low_score_chunks_are_filtered_by_threshold(self, monkeypatch):
        """低于相关性阈值的片段不进入上下文——宁可让模型拒答，也不给它噪声。"""
        monkeypatch.setattr(rag_service, "RELEVANCE_THRESHOLD", 0.5)
        results = {
            "documents": [["相关内容", "无关内容"]],
            "metadatas": [[{"doc_name": "a.md"}, {"doc_name": "b.md"}]],
            "distances": [[0.2, 0.9]],  # score = 0.8 / 0.1
        }
        context, sources = build_context_from_results(results)

        assert "相关内容" in context
        assert "无关内容" not in context
        assert [s["doc_name"] for s in sources] == ["a.md"]

    def test_sources_carry_metadata_for_citation(self, monkeypatch):
        monkeypatch.setattr(rag_service, "RELEVANCE_THRESHOLD", 0.0)
        results = {
            "documents": [["正文"]],
            "metadatas": [[{"doc_name": "手册.pdf", "doc_id": 7, "chunk_index": 3}]],
            "distances": [[0.1]],
        }
        _, sources = build_context_from_results(results)

        assert sources[0]["doc_name"] == "手册.pdf"
        assert sources[0]["doc_id"] == 7
        assert sources[0]["chunk_id"] == 3
        assert sources[0]["score"] == pytest.approx(0.9)

    def test_all_filtered_gives_explicit_empty_marker(self, monkeypatch):
        """一条都没留下时要给出明确的空标记，而不是空字符串——

        空字符串会让模型以为"参考内容是空的"从而自由发挥。
        """
        monkeypatch.setattr(rag_service, "RELEVANCE_THRESHOLD", 0.99)
        results = {
            "documents": [["噪声"]],
            "metadatas": [[{"doc_name": "x"}]],
            "distances": [[0.9]],
        }
        context, sources = build_context_from_results(results)
        assert context == "暂无相关知识库内容。"
        assert sources == []


class TestBuildRagMessages:
    def test_braces_in_document_do_not_break_prompt(self):
        """知识库里的 JSON 示例含花括号，不能触发模板变量解析。

        原实现把拼好的文本交给 ChatPromptTemplate，遇到 API 文档里的
        {"task_id": "..."} 会抛 INVALID_PROMPT_INPUT，导致整个问答失败。
        """
        from app.services.rag_service import build_rag_messages

        context = '示例：{"task_id": "abc", "status": "running"}'
        messages = build_rag_messages("怎么调用？", context)

        assert len(messages) == 2
        assert '{"task_id": "abc"' in messages[0].content

    def test_history_is_ordered_before_current_question(self):
        from app.services.rag_service import build_rag_messages

        messages = build_rag_messages(
            "那它呢？",
            "上下文",
            history=[
                {"role": "user", "content": "问题一"},
                {"role": "assistant", "content": "回答一"},
            ],
        )
        assert [m.content for m in messages[1:]] == ["问题一", "回答一", "那它呢？"]
