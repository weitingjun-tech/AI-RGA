"""日志配置。

支持两种输出格式，由 LOG_FORMAT 环境变量控制：
- text（默认）：给人看的，本地开发用
- json：给机器看的，生产环境交给 ELK / Loki / 云日志采集

两种格式都带 request_id 字段，可据此还原一次请求的完整链路。
"""
import json
import logging
import sys
from datetime import datetime, timezone

from app.config import LOG_FORMAT, LOG_LEVEL
from app.utils.request_context import RequestIdFilter


class JsonFormatter(logging.Formatter):
    """把日志输出成单行 JSON——日志采集系统按行切分，多行堆栈会打断解析。"""

    def format(self, record: logging.LogRecord) -> str:
        payload = {
            "ts": datetime.fromtimestamp(record.created, tz=timezone.utc).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "request_id": getattr(record, "request_id", "-"),
            "message": record.getMessage(),
        }
        if record.exc_info:
            payload["exception"] = self.formatException(record.exc_info)
        # 允许 logger.info(..., extra={"extra_fields": {...}}) 附加业务字段
        extra = getattr(record, "extra_fields", None)
        if isinstance(extra, dict):
            payload.update(extra)
        return json.dumps(payload, ensure_ascii=False)


def setup_logging() -> None:
    """初始化根 logger。由 main.py 在应用启动最早期调用。"""
    root = logging.getLogger()
    root.setLevel(getattr(logging, LOG_LEVEL.upper(), logging.INFO))

    # 清掉可能已存在的 handler，避免重复输出（--reload 下会重复执行）
    for handler in list(root.handlers):
        root.removeHandler(handler)

    handler = logging.StreamHandler(sys.stdout)
    if LOG_FORMAT.lower() == "json":
        handler.setFormatter(JsonFormatter())
    else:
        handler.setFormatter(
            logging.Formatter(
                "%(asctime)s [%(levelname)s] [%(request_id)s] %(name)s: %(message)s"
            )
        )
    handler.addFilter(RequestIdFilter())
    root.addHandler(handler)

    # uvicorn 自带的 access 日志和我们的请求日志重复，关掉
    logging.getLogger("uvicorn.access").disabled = True
