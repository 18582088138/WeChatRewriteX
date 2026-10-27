"""统一导出发布包（一阶段唯一 Publisher）。

每个平台一个目录：文本（可直接复制）+ 媒体文件 + README.txt 发布说明。
公众号附排版 HTML（浏览器打开后可整页复制粘贴进公众号编辑器，样式随行）。
"""
from __future__ import annotations

import html
import shutil
from pathlib import Path

from ...core import blocks as bk
from ...core import config
from ...core.models import Block, BlockType, DraftDoc, Variant
from ...storage import dao, library
from .base import Capabilities, PushResult

PLATFORMS = ["wechat_mp", "xhs", "weibo", "x"]
_PLATFORM_LABEL = {"wechat_mp": "微信公众号", "xhs": "小红书", "weibo": "微博", "x": "X"}


class Exporter:
    platform = "exporter"

    def capabilities(self) -> Capabilities:
        return Capabilities(export=True)


# ---------------- 变体生成 ----------------

def build_variant(doc: DraftDoc, platform: str) -> Variant:
    if platform == "wechat_mp":
        return Variant(platform=platform,
                       title=(doc.meta.title_candidates or [""])[0],
                       body=blocks_to_mp_html(doc),
                       media=_doc_media(doc),
                       extras={"summary": doc.meta.one_liner})
    if platform == "xhs":
        tags = " ".join(f"#{k}" for k in doc.meta.keywords[:5])
        body = f"{(doc.meta.title_candidates or [''])[0]}\n\n{doc.meta.one_liner}\n\n{tags}"
        return Variant(platform=platform, title=(doc.meta.title_candidates or [""])[0][:20],
                       body=body, extras={"cards_dir": "cards", "tags": doc.meta.keywords[:5]})
    if platform == "weibo":
        max_chars = int(config.get("variants.weibo.max_chars", 140))
        text = f"{doc.meta.one_liner}"
        if len(text) > max_chars:
            text = text[: max_chars - 1] + "…"
        tags = " ".join(f"#{k}#" for k in doc.meta.keywords[:3])
        return Variant(platform="weibo", body=f"{text} {tags}".strip(),
                       media=_doc_media(doc)[:9])
    if platform == "x":
        tweets = _x_thread(doc, int(config.get("variants.x.max_tweets", 6)))
        return Variant(platform="x", body="\n\n---\n\n".join(tweets),
                       media=_doc_media(doc)[:4], extras={"tweets": tweets})
    raise ValueError(f"未知平台: {platform}")


def _doc_media(doc: DraftDoc) -> list[str]:
    out = []
    for b in doc.blocks:
        if b.type in (BlockType.IMAGE, BlockType.VIDEO) and b.asset_id:
            m = dao.get_material(b.asset_id)
            if m and m.get("path"):
                out.append(m["path"])
    return out


def _x_thread(doc: DraftDoc, max_tweets: int) -> list[str]:
    tweets = [f"1/ {doc.meta.one_liner}"]
    n = 2
    for b in bk.iter_text_blocks(doc):
        if b.type == BlockType.HEADING:
            continue
        text = b.text.strip()
        if not text:
            continue
        while text and len(tweets) < max_tweets:
            chunk, text = text[:240], text[240:]
            tweets.append(f"{n}/ {chunk}")
            n += 1
        if len(tweets) >= max_tweets:
            break
    src = ""
    for b in doc.blocks:
        if b.citations:
            m = dao.get_material(b.citations[0])
            if m and m.get("source_url"):
                src = m["source_url"]
                break
    if src and len(tweets) < max_tweets + 1:
        tweets.append(f"来源: {src}")
    return tweets


def blocks_to_mp_html(doc: DraftDoc) -> str:
    """块 → 公众号排版 HTML（内联样式，整页可复制进公众号编辑器）。"""
    esc = html.escape
    parts = []
    for b in doc.blocks:
        text = bk.sanitize_block_text(b.text)
        if b.type == BlockType.HEADING:
            size = {1: 22, 2: 18, 3: 16}.get(b.level, 16)
            parts.append(
                f'<h{b.level} style="font-size:{size}px;font-weight:700;color:#1f2937;'
                f'margin:28px 0 14px;line-height:1.4;">{esc(text)}</h{b.level}>')
        elif b.type == BlockType.PARAGRAPH:
            parts.append(
                f'<p style="font-size:15px;line-height:1.9;color:#3f3f46;'
                f'margin:0 0 16px;text-align:justify;">{esc(text)}</p>')
        elif b.type == BlockType.QUOTE:
            parts.append(
                f'<blockquote style="margin:0 0 16px;padding:12px 16px;'
                f'border-left:4px solid #d4d4d8;background:#fafafa;color:#52525b;'
                f'font-size:14px;line-height:1.8;">{esc(text)}</blockquote>')
        elif b.type == BlockType.IMAGE and b.asset_id:
            m = dao.get_material(b.asset_id)
            if m and m.get("path"):
                src = f"media/{Path(m['path']).name}"
                cap = f'<p style="text-align:center;color:#a1a1aa;font-size:12px;margin:4px 0 20px;">{esc(b.caption or "")}</p>'
                src_note = f'<p style="text-align:center;color:#c4c4cc;font-size:11px;margin:-14px 0 20px;">图源：{esc(b.source or "")}</p>' if b.source else ""
                parts.append(
                    f'<p style="text-align:center;margin:20px 0 0;">'
                    f'<img src="{src}" style="max-width:100%;border-radius:8px;"></p>{cap}{src_note}')
        elif b.type == BlockType.DIVIDER:
            parts.append('<hr style="border:none;border-top:1px solid #e4e4e7;margin:28px 0;">')
    return ("\n".join(parts))


# ---------------- 导出 ----------------

def export_variants(article_id: str, platforms: list[str]) -> dict:
    draft = dao.latest_draft(article_id)
    if not draft:
        raise ValueError("没有草稿，先完成创作")
    doc = DraftDoc.model_validate_json(draft["doc_json"])
    # 发布包落在文章素材文件夹内：data/library/articles/<标题_短id>/exports/<平台>/
    root = library.exports_dir(article_id)
    root.mkdir(parents=True, exist_ok=True)

    results: dict[str, dict] = {}
    for platform in platforms:
        from ...core import events
        events.bus.publish(events.STAGE_PROGRESS, article_id,
                           stage="publish",
                           message=f"导出 {_PLATFORM_LABEL.get(platform, platform)} 发布包…")
        pid = dao.create_publish_job(article_id, draft["id"], platform, {})
        try:
            res = _export_one(doc, article_id, platform, root)
            events.bus.publish(events.STAGE_PROGRESS, article_id, stage="publish",
                               message=f"{_PLATFORM_LABEL.get(platform, platform)} 完成：{res.message[:60]}")
            dao.finish_publish_job(pid, res.__dict__, ok=res.ok)
        except Exception as e:
            dao.finish_publish_job(pid, {"message": str(e)}, ok=False)
            res = PushResult(ok=False, platform=platform, message=str(e))
        results[platform] = res.__dict__
    return {"article_id": article_id, "export_root": str(root), "platforms": results}


def _export_one(doc: DraftDoc, article_id: str, platform: str, root: Path) -> PushResult:
    out = root / platform
    media_dir = out / "media"
    media_dir.mkdir(parents=True, exist_ok=True)
    variant = build_variant(doc, platform)

    files: list[str] = []
    # 媒体拷贝（公众号 HTML 引用 media/ 相对路径）
    for rel in _doc_media(doc):
        src = library.material_abs_path(rel)
        if src and src.exists():
            shutil.copy2(src, media_dir / src.name)
            files.append(f"media/{src.name}")

    label = _PLATFORM_LABEL.get(platform, platform)
    if platform == "wechat_mp":
        (out / "article.html").write_text(
            f"<html><head><meta charset='utf-8'><title>{html.escape(variant.title)}</title>"
            "</head><body style='max-width:677px;margin:0 auto;padding:24px;'>"
            f"{variant.body}</body></html>", encoding="utf-8")
        (out / "article.md").write_text(bk.to_markdown(doc), encoding="utf-8")
        files += ["article.html", "article.md"]
        note = ("1. 浏览器打开 article.html，全选复制 → 粘贴进公众号编辑器（样式随行）\n"
                "2. 图片如未随行，从 media/ 目录手动上传替换\n"
                "3. 摘要可填 article.md 开头的一句话总结")
    elif platform == "xhs":
        from ..cards.render import render_cards
        cards = render_cards(article_id, out_dir=out / "cards")
        (out / "caption.txt").write_text(variant.body, encoding="utf-8")
        files += [f"cards/{p.name}" for p in cards] + ["caption.txt"]
        note = ("1. cards/ 下 page-01.png 起即为分页卡片（首张为封面），按序上传\n"
                "2. caption.txt 为标题+正文+话题标签，直接复制")
    elif platform == "weibo":
        (out / "weibo.txt").write_text(variant.body, encoding="utf-8")
        files += ["weibo.txt"]
        note = "复制 weibo.txt 文本 + 选择 media/ 图片（≤9 张）发布"
    else:  # x
        (out / "thread.txt").write_text(variant.body, encoding="utf-8")
        files += ["thread.txt"]
        note = "thread.txt 为推文串（--- 分隔逐条），按序发布；配图取 media/（≤4 张/条）"

    (out / "README.txt").write_text(
        f"平台: {label}\n标题: {variant.title}\n\n发布步骤:\n{note}\n", encoding="utf-8")
    files.append("README.txt")
    return PushResult(ok=True, platform=platform, export_dir=str(out), files=files,
                      message=f"{label}发布包已生成，请手动到平台发布")
