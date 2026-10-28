"""Typed, bounded dynamic settings. Process/storage paths require restart."""
from typing import Annotated, Literal
from pydantic import Field, TypeAdapter

Bool = Annotated[bool, Field(strict=True)]
def integer(low, high):
    return Annotated[int, Field(strict=True, ge=low, le=high)]
Ratio = Annotated[float, Field(ge=0, le=1)]

MUTABLE = {
    "collect.search_window_days": integer(0, 365),
    "collect.allow_foundational": Bool,
    "collect.ref_count.min": integer(1, 50),
    "collect.ref_count.max": integer(1, 50),
    "collect.watermark_check": Literal["heuristic", "vision", "off"],
    "create.target_word_count": integer(300, 8000),
    "create.originality_guard": Bool,
    "review.block_on_blocker": Bool,
    "review.originality.simhash_warn": Ratio,
    "review.originality.simhash_block": Ratio,
    "review.originality.embedding_warn": Ratio,
    "review.originality.embedding_block": Ratio,
    "review.recheck_on_edit.enabled": Bool,
    "review.recheck_on_edit.min_changed_blocks": integer(1, 100),
    "review.recheck_on_edit.min_word_delta_pct": Annotated[float, Field(ge=0, le=100)],
    "pipeline.auto": Bool,
    "pipeline.concurrency.download": integer(1, 16),
    "dev.mode": Bool,
    "cards.max_chars_per_page": integer(50, 2000),
    "cards.image_char_cost": integer(0, 2000),
    "variants.weibo.max_chars": integer(20, 2000),
    "variants.x.max_tweets": integer(1, 30),
    "log.level": Literal["INFO", "ERROR"],
    "log.keep_days": integer(1, 365),
}


def value_for(key: str, value):
    if key not in MUTABLE:
        raise ValueError("此配置不能通过 API 修改；路径、渠道和 hooks 请在停机后编辑配置文件")
    return TypeAdapter(MUTABLE[key]).validate_python(value)


def validate(settings: dict):
    for key in MUTABLE:
        node = settings
        for part in key.split("."):
            node = node.get(part) if isinstance(node, dict) else None
        if node is not None:
            value_for(key, node)
    refs = settings["collect"]["ref_count"]
    if refs["min"] > refs["max"]:
        raise ValueError("参考篇数下限不能大于上限")
    for prefix in ("simhash", "embedding"):
        thresholds = settings["review"]["originality"]
        if thresholds[prefix + "_warn"] > thresholds[prefix + "_block"]:
            raise ValueError("警告阈值不能大于阻断阈值")
    for key in ("pages",):
        bounds = settings["variants"]["xhs"][key]
        if not isinstance(bounds, list) or len(bounds) != 2 or not 1 <= bounds[0] <= bounds[1] <= 30:
            raise ValueError("小红书分页范围必须满足 1 ≤ min ≤ max ≤ 30")
    TypeAdapter(integer(1, 2048)).validate_python(settings["storage"]["material_size_limit_mb"])
    if not isinstance(settings["storage"]["data_dir"], str):
        raise ValueError("存储目录必须是字符串")
    return settings
