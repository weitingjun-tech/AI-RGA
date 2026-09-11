"""多轮对话的检索改写（指代消解）。

**要解决的问题**
用户在第二轮问「它支持哪些数据库？」，系统拿这句话原样去检索，
向量库里没有「它」这个东西，召回的内容和第一轮的问题毫无关系，
于是回答开始跑偏。**改写的目的只是让检索能找到正确的内容**，
最终回答的仍然是用户原本的那句话（连同完整历史一起交给模型）。

**为什么不无脑改写**
改写要额外调一次 LLM。在 CPU 上跑 qwen2.5:7b，这一次调用要 1~3 秒——
比整个向量检索还慢。如果每轮都改写，绝大多数「本来就完整」的问题
白白多等几秒，换不来任何检索质量的提升。
所以这里先做一次**廉价的启发式判断**，只在问题真的依赖上下文时才改写。

**失败必须回退**
改写是"锦上添花"，不能成为新的故障点：
模型超时、返回空、返回一段解释而不是问题——任何异常都退回原问题，
保证最差情况下系统行为和不做改写时完全一样。
"""
import logging
import re

from langchain_core.messages import HumanMessage, SystemMessage

logger = logging.getLogger("rag-app")

# ---------------------------------------------------------------------------
# 何时需要改写
# ---------------------------------------------------------------------------
# 指示代词 / 上下文指代：出现这些词说明句子本身不自足
_REFERENCE_RE = re.compile(
    r"(它|他|她|它们|这个|那个|这些|那些|该|此|上述|上面|刚才|刚刚|前面|之前|刚才说的)"
)

# 省略式追问：只有短短几个字，语义完全来自上一轮
_FOLLOWUP_RE = re.compile(r"^(那|还有|那么)?\s*(呢|吗|然后呢|怎么办|为什么|怎么弄|如何)\s*[?？]?$")

# 太短的问题几乎不可能自足（例如「报错了」「多少钱」）
_MIN_SELF_CONTAINED_LENGTH = 10

_MAX_QUERY_LENGTH = 200


def needs_rewrite(query: str, history: list[dict] | None) -> bool:
    """判断这句话是否依赖上文。

    **偏置是"拿不准就改写"**，理由是两类错误的代价完全不对等：

    - 漏判（该改写却没改）：检索拿「它支持哪些数据库」去查，什么都查不到，
      答案直接是错的。用户看到的是一个莫名其妙的回答，且不知道为什么。
    - 误判（不必改写却改了）：多花 1~3 秒，改写结果通常和原问题一样，
      答案质量不受影响。

    所以这里不追求判断精准，只负责挡掉"明显自足"的那一大类
    （完整主谓宾 + 带具体名词），它们在真实提问里占多数，挡住就够省下大头了。

    副作用要提前知道：句内的指示代词（如「ERR-5001 这个错误码是什么」）
    也会触发改写——「这个」指的是同句里的 ERR-5001，其实不需要上文。
    靠规则区分不了这种情况，而这个误判的代价只是多一次 LLM 调用。
    """
    if not history:
        return False

    text = (query or "").strip()
    if not text:
        return False

    if _FOLLOWUP_RE.match(text):
        return True
    if _REFERENCE_RE.search(text):
        return True
    # 极短的提问（「报错了」「多少钱」）几乎一定要靠上文才能理解
    return len(text) < _MIN_SELF_CONTAINED_LENGTH


# ---------------------------------------------------------------------------
# 改写
# ---------------------------------------------------------------------------
_REWRITE_SYSTEM_PROMPT = """你是一个检索查询改写助手。你的唯一任务是把用户最新的一句话改写成一个\
**不依赖对话历史、可以独立用于检索**的完整问题。

规则：
1. 只输出改写后的问题本身。不要解释，不要加引号，不要写"改写后："之类的前缀
2. 把代词（它/这个/那个/该）替换成对话历史中明确提到的具体事物
3. 如果原问题本身已经完整、不依赖上文，就原样输出，不要画蛇添足
4. 不要回答问题，你只负责改写问题
5. 保持原问题的语言（中文问就用中文）"""


def _format_history(history: list[dict], max_turns: int = 4) -> str:
    """把历史压成简短文本。

    只取最近几轮：更早的内容对指代消解没有帮助，
    全塞进去只会拖慢推理、稀释注意力。
    """
    recent = history[-max_turns * 2 :]
    lines = []
    for msg in recent:
        role = "用户" if msg.get("role") == "user" else "助手"
        content = (msg.get("content") or "").strip().replace("\n", " ")
        # 助手回答可能很长，截断即可——改写只需要知道"在聊什么话题"
        lines.append(f"{role}：{content[:120]}")
    return "\n".join(lines)


# 模型不守规矩时爱加的客套前缀
_PREAMBLE_PREFIXES = ("改写后：", "改写后:", "改写：", "改写:", "问题：", "问题:")


def _clean_rewritten(text: str, original: str) -> str:
    """清洗模型输出，不合格就退回原问题。

    小模型（7B 级别）经常不守规矩，实测三种典型跑偏：
      1. 给结果加引号或"改写后："前缀
      2. 先客套一句「好的，我来改写：」，下一行才是真正的问题
      3. 干脆把答案写出来
    这些都不能直接拿去检索，否则检索的是一句废话。
    """
    if not text:
        return original

    lines = [ln.strip().strip('"\'“”‘’').strip() for ln in text.strip().splitlines()]
    lines = [ln for ln in lines if ln]
    if not lines:
        return original

    cleaned = lines[0]

    # 情况 1：以冒号结尾 → 这是引言不是问题，真正的问题在下一行
    # （必须有下一行才切换，否则「配置了哪些参数？」这种以问号结尾的正常问题会被误伤；
    #   而以冒号结尾的句子不可能是完整问题。）
    if cleaned.endswith(("：", ":")) and len(lines) > 1:
        cleaned = lines[1]

    for prefix in _PREAMBLE_PREFIXES:
        if cleaned.startswith(prefix):
            cleaned = cleaned[len(prefix) :].strip()

    if not cleaned or len(cleaned) > _MAX_QUERY_LENGTH:
        logger.warning(f"改写结果不合格，回退原问题: {text[:80]!r}")
        return original

    return cleaned


def rewrite_query(query: str, history: list[dict] | None, llm=None) -> str:
    """把依赖上文的追问改写成可独立检索的问题。

    Args:
        llm: 可注入的 LLM 实例（测试用）。默认用 rag_service.get_llm()。

    Returns:
        改写后的问题；不需要改写或改写失败时，返回**原问题**。

    这个函数**从不抛异常**——它是问答链路的前置优化，
    不能因为一次改写失败就让整个提问失败。
    """
    if not needs_rewrite(query, history):
        return query

    try:
        if llm is None:
            # 延迟导入：避免与本模块的单元测试形成循环依赖，
            # 也避免 import 阶段就去初始化 LLM 客户端
            from app.services.rag_service import get_llm

            llm = get_llm()

        messages = [
            SystemMessage(content=_REWRITE_SYSTEM_PROMPT),
            HumanMessage(
                content=f"对话历史：\n{_format_history(history or [])}\n\n"
                f"用户最新的一句话：{query}\n\n改写后的问题："
            ),
        ]
        raw = llm.invoke(messages)
        rewritten = _clean_rewritten(getattr(raw, "content", str(raw)), query)

        if rewritten != query:
            logger.info(f"检索改写: {query!r} -> {rewritten!r}")
        return rewritten

    except Exception as exc:
        # 任何异常都退回原问题：最差情况等价于"没做改写"，
        # 而不是"提问失败"
        logger.warning(f"检索改写失败，使用原问题: {exc}")
        return query
