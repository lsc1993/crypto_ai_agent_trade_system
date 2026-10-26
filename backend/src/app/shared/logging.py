# 配置标准 logging 与 structlog 的 JSON 输出。
# 合并上下文变量、附加级别和 UTC 时间戳，再序列化结构化字段。
# 处理器不自动过滤凭证或模型原文，调用方必须只提供允许记录的元数据。
import logging

import structlog


# 接收日志级别并配置进程日志器；未知名称使用 INFO，输出字段仍需调用者约束。
def configure_logging(log_level: str) -> None:
    normalized_level = log_level.upper()
    numeric_level = logging.getLevelNamesMapping().get(normalized_level, logging.INFO)

    logging.basicConfig(
        format="%(message)s",
        level=numeric_level,
    )
    structlog.configure(
        processors=[
            structlog.contextvars.merge_contextvars,
            structlog.processors.add_log_level,
            structlog.processors.TimeStamper(fmt="iso", utc=True),
            structlog.processors.JSONRenderer(),
        ],
        wrapper_class=structlog.make_filtering_bound_logger(numeric_level),
        logger_factory=structlog.stdlib.LoggerFactory(),
        cache_logger_on_first_use=True,
    )
