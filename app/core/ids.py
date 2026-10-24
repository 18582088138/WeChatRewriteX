"""带前缀的短 id 生成，便于日志与调试中一眼识别实体类型。"""
from __future__ import annotations

import uuid

_PREFIXES = {
    "article": "art",
    "material": "mat",
    "draft": "drf",
    "review": "rev",
    "review_item": "ri",
    "job": "job",
    "target": "tgt",
    "publish_job": "pj",
}


def new_id(kind: str) -> str:
    prefix = _PREFIXES.get(kind, kind[:4])
    return f"{prefix}_{uuid.uuid4().hex[:12]}"
