# 提供关键词知识检索的确定性纯函数：词项规范化、分块、块指纹与 4:1 匹配评分。
# 该模块不依赖数据库、Agent、Embedding、网络或交易执行，供契约校验和 SQL 仓储复用。
# 规范化只影响索引词项，不改写或截断返回给用户的原文片段。
from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass
from hashlib import sha256
from uuid import NAMESPACE_URL, UUID, uuid5

# 契约固定的索引参数：单文档 256 KiB、1000 字符分块、100 字符重叠、最多 6 块命中。
MAX_DOCUMENT_BYTES = 256 * 1024
CHUNK_SIZE = 1000
CHUNK_OVERLAP = 100
MAX_HITS = 6
MAX_QUERY_TERMS = 64

# NFKC 后英文按连续字母数字切词，中文连续表意文字按相邻双字切词。
_TOKEN_PATTERN = re.compile(
    r"[a-z0-9]+|[\u3400-\u4dbf\u4e00-\u9fff\uf900-\ufaff]+",
)
_CJK_RANGES = (
    ("\u3400", "\u4dbf"),
    ("\u4e00", "\u9fff"),
    ("\uf900", "\ufaff"),
)


# 分块计划是导入事务的纯输入；标题词项与正文词项分开保存，用于固定 4:1 评分。
@dataclass(frozen=True)
class PreparedChunk:
    chunk_id: UUID
    chunk_index: int
    text: str
    sha256: str
    terms: tuple[str, ...]
    title_terms: tuple[str, ...]


# 判断字符是否属于索引支持的中文表意文字范围；其他文字不生成中文双字词。
def _is_cjk(character: str) -> bool:
    return any(start <= character <= end for start, end in _CJK_RANGES)


# NFKC 规范化、英文小写和中文双字切词；词项按首次出现顺序去重。
# 该函数只产生索引键，不返回修改后的正文，避免展示文本被规范化改写。
def tokenize(text: str) -> tuple[str, ...]:
    normalized = unicodedata.normalize("NFKC", text).lower()
    terms: dict[str, None] = {}
    for match in _TOKEN_PATTERN.finditer(normalized):
        piece = match.group(0)
        if piece and piece[0].isascii():
            terms.setdefault(piece, None)
            continue
        # 单个孤立的汉字没有双字词项，不能凭单字制造模糊匹配；显式查询会由查询契约拒绝。
        for index in range(len(piece) - 1):
            pair = piece[index : index + 2]
            if _is_cjk(pair[0]) and _is_cjk(pair[1]):
                terms.setdefault(pair, None)
    return tuple(terms)


# 按 Unicode 字符切块并保留原文；最后一块覆盖到文本末尾，短于重叠时不重复追加。
def chunk_text(text: str) -> tuple[str, ...]:
    if not text:
        return ()
    count = _chunk_count(len(text))
    return tuple(chunk_at(text, index) for index in range(count))


# 返回指定块序号对应的原文切片；供数据库防护、检索一致性和测试共用。
# 第 index 块的起点固定为 index * (CHUNK_SIZE - CHUNK_OVERLAP)，越界返回空串。
def chunk_at(text: str, chunk_index: int) -> str:
    if chunk_index < 0:
        raise ValueError("知识分块序号不能为负")
    start = chunk_index * (CHUNK_SIZE - CHUNK_OVERLAP)
    if start >= len(text):
        return ""
    return text[start : start + CHUNK_SIZE]


# 由文本长度推导块数；1..1000 字符为 1 块，之后按 900 字符步长递增。
def _chunk_count(length: int) -> int:
    if length <= CHUNK_SIZE:
        return 1
    step = CHUNK_SIZE - CHUNK_OVERLAP
    return 1 + (length - CHUNK_SIZE + step - 1) // step


# 计算 UTF-8 原文或片段指纹；用于版本引用和命中校验，不改变内容。
def sha256_text(text: str) -> str:
    return sha256(text.encode("utf-8")).hexdigest()


# 由版本 ID、块序号和块指纹派生稳定块 ID；同一版本重建分块不会得到随机 ID。
def chunk_id_for(version_id: UUID, chunk_index: int, chunk_sha256: str) -> UUID:
    return uuid5(
        NAMESPACE_URL,
        f"knowledge-chunk:{version_id}:{chunk_index}:{chunk_sha256}",
    )


# 为一次导入生成全部不可变分块；标题词项重复存放在每块上，供 SQL 直接计算标题权重。
def prepare_chunks(version_id: UUID, title: str, text: str) -> tuple[PreparedChunk, ...]:
    title_terms = tokenize(title)
    prepared: list[PreparedChunk] = []
    for chunk_index, chunk in enumerate(chunk_text(text)):
        digest = sha256_text(chunk)
        prepared.append(
            PreparedChunk(
                chunk_id=chunk_id_for(version_id, chunk_index, digest),
                chunk_index=chunk_index,
                text=chunk,
                sha256=digest,
                terms=tokenize(chunk),
                title_terms=title_terms,
            )
        )
    return tuple(prepared)


# 固定评分：标题每命中一个去重词项 4 分，正文每命中一个去重词项 1 分。
# 分数只是确定性排序依据，不是概率、相关度置信度或质量承诺。
def score_chunk(
    title_terms: tuple[str, ...],
    body_terms: tuple[str, ...],
    query_terms: tuple[str, ...],
) -> int:
    query = set(query_terms)
    return 4 * len(set(title_terms) & query) + len(set(body_terms) & query)


__all__ = [
    "CHUNK_OVERLAP",
    "CHUNK_SIZE",
    "MAX_DOCUMENT_BYTES",
    "MAX_HITS",
    "MAX_QUERY_TERMS",
    "PreparedChunk",
    "chunk_at",
    "chunk_id_for",
    "chunk_text",
    "prepare_chunks",
    "score_chunk",
    "sha256_text",
    "tokenize",
]
