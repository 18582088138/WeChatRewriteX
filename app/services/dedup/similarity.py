"""文本查重：字符 n-gram shingles + SimHash + Jaccard（无第三方依赖）。

- simhash_similarity: 64 位海明相似度，适合大批量粗筛
- jaccard: shingle 集合交并比，作为字面相似度主指标
中文不依赖分词，直接用字符 4-gram，对「逐句改写」检测更敏感。
"""
from __future__ import annotations

import hashlib
import re

_N = 4
_BITS = 64


def normalize(text: str) -> str:
    t = re.sub(r"\s+", "", text)
    t = re.sub(r"[，。！？；：、“”‘’（）《》〈〉【】…—·,.!?;:\"'()\[\]<>-]", "", t)
    return t.lower()


def shingles(text: str, n: int = _N) -> set[str]:
    t = normalize(text)
    if len(t) <= n:
        return {t} if t else set()
    return {t[i:i + n] for i in range(len(t) - n + 1)}


def jaccard(a: str, b: str) -> float:
    sa, sb = shingles(a), shingles(b)
    if not sa or not sb:
        return 0.0
    return len(sa & sb) / len(sa | sb)


def _hash64(s: str) -> int:
    return int.from_bytes(hashlib.md5(s.encode("utf-8")).digest()[:8], "little")


def simhash(text: str) -> int:
    v = [0] * _BITS
    for sh in shingles(text):
        h = _hash64(sh)
        for i in range(_BITS):
            v[i] += 1 if (h >> i) & 1 else -1
    out = 0
    for i in range(_BITS):
        if v[i] > 0:
            out |= 1 << i
    return out


def simhash_similarity(a: str, b: str) -> float:
    ha, hb = simhash(a), simhash(b)
    dist = bin(ha ^ hb).count("1")
    return 1.0 - dist / _BITS


def literal_similarity(a: str, b: str) -> dict:
    """字面相似度综合视图，供审稿 originality 维度使用。"""
    return {"jaccard": round(jaccard(a, b), 4),
            "simhash": round(simhash_similarity(a, b), 4)}
