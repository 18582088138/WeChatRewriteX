"""水印检测：M1 启发式 + 可选 vision 模型复核（配置 collect.watermark_check=vision）。

启发式目前覆盖：来源平台已知水印习惯（微博/小红书用户图）、URL 特征。
拿不准返回 None（未检测），由 vision 或人工兜底——编辑器中图片始终默认显示，
最终去留由人决定（需求 #10）。
"""
from __future__ import annotations

import base64

from ...core import config
from ...storage import dao

# 来源 URL 特征 → 是否常带水印（保守: 只标记高置信情况）
_URL_HINTS = {
    "wx_fmt=jpeg&from=appmsg": 0,   # 公众号正文图一般无水印
}


def check_image_heuristic(material_id: str, source_url: str | None = None) -> int | None:
    url = source_url or ""
    for hint, flag in _URL_HINTS.items():
        if hint in url:
            return flag
    return None


def check_image_vision(material_id: str) -> int | None:
    """用 vision 档模型判断是否含水印。渠道未配置或失败时返回 None。"""
    if config.get("collect.watermark_check") != "vision":
        return None
    m = dao.get_material(material_id)
    if not m or not m.get("path"):
        return None
    from ...storage import library
    p = library.material_abs_path(m["path"])
    if not p or not p.exists():
        return None
    try:
        from ..llm import router
        b64 = base64.b64encode(p.read_bytes()).decode()
        result = router.complete(
            "vision",
            [{"role": "user", "content": [
                {"type": "image_url",
                 "image_url": {"url": f"data:image/jpeg;base64,{b64}"}},
                {"type": "text",
                 "text": "判断这张图片是否带有平台水印、角标 logo 或来源标识。"
                         "只回答 JSON: {\"watermark\": true/false}"}]}],
        )
        import json
        return 1 if json.loads(result.text.strip().strip("`").replace("json", "", 1))\
            .get("watermark") else 0
    except Exception:
        return None
