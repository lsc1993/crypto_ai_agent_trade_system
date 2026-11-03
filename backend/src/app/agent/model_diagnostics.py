# 将框架错误类型映射为固定诊断类别；不读取输入值、错误消息或上下文，避免泄漏模型原文。
from collections.abc import Iterable


def schema_error_kinds(error_types: Iterable[str]) -> tuple[str, ...]:
    """只输出固定类别，供有界纠错和本地安全评估；未知框架类型也不会原样回传。"""
    kinds: set[str] = set()
    for value in error_types:
        if value in {"enum", "literal_error"}:
            kinds.add("enum")
        elif value == "missing":
            kinds.add("missing_field")
        elif value == "extra_forbidden":
            kinds.add("extra_field")
        elif value == "json_invalid":
            kinds.add("json")
        elif value in {"too_long", "too_short", "string_too_long", "string_too_short"}:
            kinds.add("length")
        elif value.endswith(("_type", "_parsing")):
            kinds.add("wrong_type")
        else:
            kinds.add("value_constraint")
    return tuple(sorted(kinds))
