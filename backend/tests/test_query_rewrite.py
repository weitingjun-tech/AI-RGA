"""多轮检索改写测试。

重点不在"能不能改写成功"，而在两条**边界**：
  1. 不该改写的时候，一次 LLM 都不能调（否则每轮白等 1~3 秒）
  2. 改写失败时，必须静默退回原问题（绝不能因此让提问失败）
"""
import pytest

from app.services import query_rewrite
from app.services.query_rewrite import (
    _clean_rewritten,
    _format_history,
    needs_rewrite,
    rewrite_query,
)

HISTORY = [
    {"role": "user", "content": "CloudFlow 支持哪些数据源？"},
    {"role": "assistant", "content": "支持 MySQL、PostgreSQL、Oracle 等关系型数据库……"},
]


class TestNeedsRewrite:
    def test_no_history_never_rewrites(self):
        """第一轮没有上文，改写无从下手，也毫无必要。"""
        assert needs_rewrite("它支持哪些数据库？", []) is False
        assert needs_rewrite("它支持哪些数据库？", None) is False

    @pytest.mark.parametrize(
        "query",
        [
            "它支持哪些数据库？",
            "这个报错怎么解决",
            "那个功能怎么开启",
            "该参数是什么意思",
            "上述步骤的第三步是什么",
            "刚才说的那个配置在哪",
        ],
    )
    def test_pronouns_trigger_rewrite(self, query):
        assert needs_rewrite(query, HISTORY) is True

    @pytest.mark.parametrize("query", ["然后呢？", "那怎么办", "还有吗", "为什么？", "呢？"])
    def test_elliptical_followups_trigger_rewrite(self, query):
        assert needs_rewrite(query, HISTORY) is True

    def test_short_queries_trigger_rewrite(self):
        """「报错了」「多少钱」这类短句几乎一定依赖上文。"""
        assert needs_rewrite("报错了", HISTORY) is True

    @pytest.mark.parametrize(
        "query",
        [
            "CloudFlow 支持哪些数据源？",
            "如何配置 MySQL 的连接超时参数？",
            "ERR-5001 错误码代表什么含义？",
            "数据同步任务的失败重试策略是怎样的？",
        ],
    )
    def test_self_contained_questions_are_left_alone(self, query):
        assert needs_rewrite(query, HISTORY) is False

    def test_in_sentence_demonstrative_still_triggers(self):
        """记录一个已知的误判：句内指示代词也会触发改写。

        「ERR-5001 这个错误码是什么」里的「这个」指的是同句中的 ERR-5001，
        其实不需要上文。但规则分不清「指代句内」和「指代上文」，
        而误判的代价只是多一次 LLM 调用，漏判的代价是检索彻底跑偏——
        所以选择接受这个误判。
        """
        assert needs_rewrite("ERR-5001 这个错误码代表什么含义？", HISTORY) is True

    def test_empty_query(self):
        assert needs_rewrite("", HISTORY) is False
        assert needs_rewrite("   ", HISTORY) is False


class TestCleanRewritten:
    def test_strips_quotes(self):
        assert _clean_rewritten('"CloudFlow 支持哪些数据库？"', "原问题") == "CloudFlow 支持哪些数据库？"
        assert _clean_rewritten("“CloudFlow 支持什么”", "原问题") == "CloudFlow 支持什么"

    def test_strips_common_prefixes(self):
        assert _clean_rewritten("改写后：CloudFlow 支持什么", "原问题") == "CloudFlow 支持什么"
        assert _clean_rewritten("问题: CloudFlow 支持什么", "原问题") == "CloudFlow 支持什么"

    def test_preamble_ending_with_colon_is_skipped(self):
        """小模型爱先客套一句「好的，我来改写：」，真正的问题在下一行。

        若不做这一步，检索的就是「好的，我来改写：」这句废话。
        """
        raw = "好的，我来改写：\nCloudFlow 支持哪些数据库？"
        assert _clean_rewritten(raw, "原问题") == "CloudFlow 支持哪些数据库？"

    def test_drops_trailing_explanation(self):
        raw = "\n\nCloudFlow 支持哪些数据库？\n（以上为改写结果）"
        assert _clean_rewritten(raw, "原问题") == "CloudFlow 支持哪些数据库？"

    def test_normal_question_is_not_mistaken_for_a_preamble(self):
        """正常问题以问号结尾，不该被"跳过第一行"的逻辑误伤。"""
        assert _clean_rewritten("CloudFlow 支持哪些数据库？", "原问题") == "CloudFlow 支持哪些数据库？"
        assert _clean_rewritten("配置在哪：", "原问题") == "配置在哪：", (
            "只有冒号却无下一行时，应当保留原样而不是回退"
        )

    def test_empty_output_falls_back(self):
        assert _clean_rewritten("", "原问题") == "原问题"
        assert _clean_rewritten("   ", "原问题") == "原问题"

    def test_overlong_output_falls_back(self):
        """模型偶尔会把整段答案吐出来，这种结果拿去做检索只会更糟。"""
        assert _clean_rewritten("很长的内容" * 100, "原问题") == "原问题"


class TestRewriteQuery:
    class _FakeLLM:
        def __init__(self, content=None, error=None):
            self.content = content
            self.error = error
            self.calls = 0

        def invoke(self, _messages):
            self.calls += 1
            if self.error:
                raise self.error

            class _Msg:
                pass

            m = _Msg()
            m.content = self.content
            return m

    def test_rewrites_when_needed(self):
        llm = self._FakeLLM(content="CloudFlow 支持哪些数据库？")
        result = rewrite_query("它支持哪些数据库？", HISTORY, llm=llm)
        assert result == "CloudFlow 支持哪些数据库？"
        assert llm.calls == 1

    def test_does_not_call_llm_when_not_needed(self):
        """**最重要的一条**：问题本身完整时，一次 LLM 调用都不能发生。

        改写要额外跑一次大模型（CPU 上 1~3 秒），
        比整个向量检索都慢。无脑改写会让每次提问都白白变慢。
        """
        llm = self._FakeLLM(content="不该被调用")
        result = rewrite_query("CloudFlow 支持哪些数据源？", HISTORY, llm=llm)

        assert result == "CloudFlow 支持哪些数据源？"
        assert llm.calls == 0, "不需要改写时不应产生任何 LLM 调用"

    def test_no_history_does_not_call_llm(self):
        llm = self._FakeLLM(content="不该被调用")
        assert rewrite_query("它呢？", [], llm=llm) == "它呢？"
        assert llm.calls == 0

    def test_llm_exception_falls_back_to_original(self):
        """改写失败必须静默回退——最差等价于"没做改写"，而不是"提问失败"。"""
        llm = self._FakeLLM(error=TimeoutError("ollama 超时"))
        assert rewrite_query("它支持哪些数据库？", HISTORY, llm=llm) == "它支持哪些数据库？"

    def test_garbage_output_falls_back(self):
        llm = self._FakeLLM(content="")
        assert rewrite_query("它支持哪些数据库？", HISTORY, llm=llm) == "它支持哪些数据库？"

    def test_llm_answering_instead_of_rewriting_still_returns_something(self):
        """模型不守规矩去回答问题时，结果仍会被清洗后使用。

        这里不断言"一定回退"——因为无法从文本上区分"改写"和"回答"。
        能做的是长度上限兜底，避免把一大段答案塞进检索。
        """
        llm = self._FakeLLM(content="支持 MySQL。" * 200)
        assert rewrite_query("它支持哪些数据库？", HISTORY, llm=llm) == "它支持哪些数据库？"


class TestFormatHistory:
    def test_includes_both_roles(self):
        text = _format_history(HISTORY)
        assert "用户：" in text and "助手：" in text

    def test_truncates_long_assistant_answers(self):
        """改写只需要知道"在聊什么话题"，助手的长篇回答没必要全塞进去。"""
        long_history = [
            {"role": "user", "content": "问题"},
            {"role": "assistant", "content": "答" * 5000},
        ]
        assert len(_format_history(long_history)) < 1000

    def test_keeps_only_recent_turns(self):
        many = [
            {"role": "user", "content": f"第{i}个问题"} for i in range(50)
        ]
        text = _format_history(many, max_turns=2)
        assert "第0个问题" not in text
        assert "第49个问题" in text

    def test_newlines_are_flattened(self):
        """历史里的换行要压掉：多条消息各占一行，否则模型分不清哪行是哪个角色说的。"""
        history = [{"role": "user", "content": "第一行\n第二行"}]
        assert "第一行 第二行" in _format_history(history)
