# 加载随包发布、已审查的静态研究方法，并校验改写文本的预期指纹。
# 原始技能只保留来源与改写说明，不执行其指令、脚本或外部数据采集。
"""Reviewed, static method bundle with provenance from the original runtime Skills.

The source Skills are untrusted reference material. Only these curated resources are
read at runtime; no source instructions, scripts, tools or external data are executed.
"""

from __future__ import annotations

from hashlib import sha256
from importlib.resources import files

from app.reports.technical import TechnicalMethod

METHOD_VERSION = "technical-v1"
_EXPECTED_ADAPTED_SHA256 = {
    "volume_price": "f3e2567837e7ef514bb366905e3ee69d454d46288feeaacefbbefa6e8d97f2ce",
    "range_breakout": "fd8fc373630d9d0caeb6a959308402d0a7e3b0df3f6f7adb9978f0d04a3faa71",
    "multi_timeframe": "8c2091eee8f204a241a92423d450423f7671ec113f20ea714a4f2ded0d301827",
    "reversal": "6f128a731c7c3f9d6b508577600f91955c7b240edf01f96d32d6729f082568d9",
}
_METHODS = (
    (
        "volume_price",
        "skill-ab92c878c6271679",
        "93908ed40ae8f70ed795e9e2643d7233896e400d83328fdff255303bd7a0fa1d",
        "删除内幕参与和确定性供需断言；加入可复现项目阈值。",
    ),
    (
        "range_breakout",
        "skill-af2777a94beff1c0",
        "1fa5b80d245fe5b61e92b177a63cd1808163732fb79c955dd91877aab3d6be6b",
        "删除主力操纵、持仓操作和凭常识画位；限定已确认结构和成本门槛。",
    ),
    (
        "multi_timeframe",
        "skill-2a5187a02dac3ed0",
        "568d36f7f8c1520c09995ea51e432e5f2649639bfd2f2e6fd37a0e94406aeF20".lower(),
        "删除账户与执行建议；固定日线、四小时和一小时的研究范围。",
    ),
    (
        "reversal",
        "skill-ae0db79a49a31fa0",
        "fdb5e561082a178a038b3d85aad5eac2a118c5e837392ef1c5021245bc6f686a",
        "删除操纵意图、身份与确定反转判断；仅保留待确认形态观察。",
    ),
)


def _text(method_id: str) -> str:
    return (files("app.agent.technical") / "methods" / f"{method_id}.md").read_text(
        encoding="utf-8"
    )


# 运行时校验方法文本完整性；注释任务不能修改方法资源，否则改变指纹与模型输入。
def _verified_hash(method_id: str) -> str:
    digest = sha256(_text(method_id).encode("utf-8")).hexdigest()
    if digest != _EXPECTED_ADAPTED_SHA256[method_id]:
        raise ValueError("技术研究方法版本与文本指纹不匹配")
    return digest


# 默认使用三个固定方法，仅在确定性形态条件满足时附加反转方法描述。
def selected_methods(*, include_reversal: bool = False) -> tuple[TechnicalMethod, ...]:
    selected = _METHODS if include_reversal else _METHODS[:3]
    return tuple(
        TechnicalMethod(
            id=method_id,
            version=METHOD_VERSION,
            source_skill_id=source_skill_id,
            source_sha256=source_sha256,
            adapted_sha256=_verified_hash(method_id),
            adaptation_note=adaptation_note,
        )
        for method_id, source_skill_id, source_sha256, adaptation_note in selected
    )


# 只返回冻结描述对应的批准文本，未知标识、版本或改写指纹不匹配时拒绝。
def method_instructions(methods: tuple[TechnicalMethod, ...] | None = None) -> str:
    """Return only approved text corresponding to the frozen method descriptors."""
    selected = methods if methods is not None else selected_methods()
    known = {method[0] for method in _METHODS}
    if any(method.id not in known for method in selected):
        raise ValueError("未知技术研究方法")
    for method in selected:
        if method.version != METHOD_VERSION or _verified_hash(method.id) != method.adapted_sha256:
            raise ValueError("技术研究方法指纹不匹配")
    return "\n\n".join(_text(method.id) for method in selected)
