# 定义模型单次输入的保守控长口径：UTF-8 请求字节数加固定协议/工具 Schema 包络。
# 该模块只做纯计算，不读取供应商计数器、不访问数据库、不调用模型或工具。
# 估算值用于发送前预留，不能当作供应商返回的真实 Token 用量或账单。
from __future__ import annotations

# 协议开销、工具 Schema 和供应商消息包装的保守包络；真实计数不可得时始终计入。
CONSERVATIVE_PROTOCOL_ENVELOPE = 4_096

# 与 C5/T05 的单次模型输入上限保持一致；T08 不另造更宽的窗口。
MAX_INPUT_UNITS_PER_CALL = 16_384


# 以最终 UTF-8 JSON 请求字节数加固定包络作为保守输入预留。
# 输入必须是已编码字节；调用方不能把 Python 字符数或未编码对象当作长度。
def estimate_input(payload: bytes) -> int:
    # 先放宽为 object 再校验，既保持运行期防御，也避免类型检查器把 bytes 参数视为多余分支。
    value: object = payload
    if not isinstance(value, bytes):  # pyright: ignore[reportUnnecessaryIsInstance]
        raise TypeError("输入预留必须基于已编码的 UTF-8 字节载荷")
    return len(value) + CONSERVATIVE_PROTOCOL_ENVELOPE


__all__ = [
    "CONSERVATIVE_PROTOCOL_ENVELOPE",
    "MAX_INPUT_UNITS_PER_CALL",
    "estimate_input",
]
