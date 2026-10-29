"""统一导出发布包（一阶段唯一 Publisher）。

每个平台一个目录：文本（可直接复制）+ 媒体文件 + README.txt 发布说明。
公众号附排版 HTML（浏览器打开后可整页复制粘贴进公众号编辑器，样式随行）。
"""
from __future__ import annotations

import html
import shutil
import hashlib
import json
import uuid
from pathlib import Path

from ...core import blocks as bk
from ...core import config
from ...core.models import Block, BlockType, DraftDoc, Variant
from ...storage import dao, library
from ...core.files import sha256_file
from .. import assets
from .base import Capabilities, PushResult
from .text_rules import split_x, truncate_x, weighted_length

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
        from .. import brand
        max_chars = int(config.get("variants.weibo.max_chars", 140))
        # This is a configurable summary target, not a universal Weibo platform cap.
        suffix = "\n\n" + brand.SLOGAN
        available = max(0, max_chars - len(suffix))
        tags = ""
        for keyword in doc.meta.keywords[:3]:
            candidate = (tags + " " + f"#{keyword}#").strip()
            if len(candidate) <= available // 2:
                tags = candidate
        budget = max(0, available - len(tags) - bool(tags))
        text = doc.meta.one_liner
        text = (text[:budget - 1] + "…") if budget and len(text) > budget else text[:budget]
        return Variant(platform="weibo", body=(text + (" " + tags if tags else "")).strip() + suffix,
                       media=_social_media(doc, 9), extras={"summary_target": max_chars})
    if platform == "x":
        tweets, truncated = _x_thread_details(doc, int(config.get("variants.x.max_tweets", 6)))
        return Variant(platform="x", body="\n\n---\n\n".join(tweets),
                       media=_social_media(doc, 4), extras={"tweets": tweets,
                       "weighted_lengths": [weighted_length(t) for t in tweets],
                       "truncated": truncated})
    raise ValueError(f"未知平台: {platform}")


def _doc_media(doc: DraftDoc) -> list[str]:
    out = []
    for b in doc.blocks:
        if b.type in (BlockType.IMAGE, BlockType.VIDEO) and b.asset_id:
            m = assets.get_material(b.asset_id)
            if m and m.get("path"):
                if m["path"] not in out:
                    out.append(m["path"])
    return out


def _social_media(doc: DraftDoc, image_limit: int) -> list[str]:
    paths = _doc_media(doc)
    images = [p for p in paths if Path(p).suffix.lower() in (".jpg", ".jpeg", ".png", ".webp")]
    # Export an explicit single media mode; never suggest mixed photos/GIF/video.
    return images[:image_limit] if images else [p for p in paths if Path(p).suffix.lower() in (".gif", ".mp4", ".mov", ".webm")][:1]


def _thread_content(doc: DraftDoc) -> tuple[str, str]:
    from .. import brand
    text = "\n\n".join([doc.meta.one_liner.strip()] + [b.text.strip()
           for b in bk.iter_text_blocks(doc) if b.type != BlockType.HEADING and b.text.strip()])
    source = next((r.get("url") for r in doc.meta.ref_links if r.get("url")), "")
    if not source:
        for block in doc.blocks:
            for mid in block.citations:
                material = assets.get_material(mid)
                if material and material.get("source_url"):
                    source = material["source_url"]
                    break
            if source:
                break
    trailer = (f"来源: {source}\n\n" if source else "") + brand.SLOGAN
    return text, truncate_x(trailer, 276)


def _x_thread_details(doc: DraftDoc, max_tweets: int) -> tuple[list[str], bool]:
    limit = max(1, min(max_tweets, 30))
    text, trailer = _thread_content(doc)
    if limit == 1:
        trailer = truncate_x(trailer, 200)
        budget = 276 - weighted_length(trailer) - 2
        body = truncate_x(text, max(2, budget))
        return [f"1/ {body}\n\n{trailer}"], weighted_length(text) > budget
    chunks = split_x(text)
    truncated = len(chunks) > limit - 1
    selected = chunks[:limit - 1]
    if truncated:
        selected[-1] = truncate_x(selected[-1] + "…", 276)
    selected.append(trailer)
    return [f"{i}/ {chunk}" for i, chunk in enumerate(selected, 1)], truncated


def _x_thread(doc: DraftDoc, max_tweets: int) -> list[str]:
    return _x_thread_details(doc, max_tweets)[0]


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
            m = assets.get_material(b.asset_id)
            if m and m.get("path"):
                src = f"media/{Path(m['path']).name}"
                cap = f'<p style="text-align:center;color:#a1a1aa;font-size:12px;margin:4px 0 20px;">{esc(b.caption or "")}</p>'
                src_note = f'<p style="text-align:center;color:#c4c4cc;font-size:11px;margin:-14px 0 20px;">图源：{esc(b.source or "")}</p>' if b.source else ""
                parts.append(
                    f'<p style="text-align:center;margin:20px 0 0;">'
                    f'<img src="{src}" style="max-width:100%;border-radius:8px;"></p>{cap}{src_note}')
        elif b.type == BlockType.VIDEO and b.asset_id:
            # 视频块（V1.12）：公众号 HTML 内嵌 <video>，随包 media/ 携带实体文件
            m = assets.get_material(b.asset_id)
            if m and m.get("path"):
                src = f"media/{Path(m['path']).name}"
                cap = f'<p style="text-align:center;color:#a1a1aa;font-size:12px;margin:4px 0 20px;">{esc(b.caption or "")}</p>'
                parts.append(
                    f'<p style="text-align:center;margin:20px 0 0;">'
                    f'<video src="{src}" controls preload="metadata" '
                    f'style="max-width:100%;border-radius:8px;background:#000;"></video></p>{cap}')
        elif b.type == BlockType.DIVIDER:
            parts.append('<hr style="border:none;border-top:1px solid #e4e4e7;margin:28px 0;">')
    return ("\n".join(parts))


# ---------------- 导出 ----------------

def export_variants(article_id: str, platforms: list[str], snapshot_id: str | None = None,
                    asset_manifest: dict | None = None) -> dict:
    draft = dao.get_draft_by_id(snapshot_id) if snapshot_id else dao.latest_draft(article_id)
    if not draft:
        raise ValueError("没有草稿，先完成创作")
    doc = DraftDoc.model_validate_json(draft["doc_json"])
    # 发布包落在文章素材文件夹内：data/library/articles/<标题_短id>/exports/<平台>/
    if draft["article_id"] != article_id:
        raise ValueError("快照不属于该文章")
    if any(platform not in PLATFORMS for platform in platforms) or not platforms:
        raise ValueError("未知或空平台列表")
    from ..draft_service import content_hash
    digest = content_hash(doc)
    # Staging is outside the movable article folder; title changes cannot invalidate it.
    staging_root = library.library_root() / ".export-staging"
    staging_root.mkdir(parents=True, exist_ok=True)
    results: dict[str, dict] = {}
    for platform in dict.fromkeys(platforms):
        from ...core import events
        events.bus.publish(events.STAGE_PROGRESS, article_id, stage="publish",
                           message=f"导出 {_PLATFORM_LABEL.get(platform, platform)} 发布包…")
        pid = dao.create_publish_job(article_id, draft["id"], platform, {})
        staging = staging_root / uuid.uuid4().hex
        backup = staging_root / ("backup-" + uuid.uuid4().hex)
        try:
            with assets.frozen(doc, staging / "assets", asset_manifest):
                res = _export_one(doc, article_id, platform, staging)
            if not res.ok:
                raise ValueError(res.message or "平台生成失败")
            output = staging / platform
            hashes = {p.relative_to(output).as_posix(): sha256_file(p)
                      for p in output.rglob("*") if p.is_file() and not p.name.startswith("_")}
            (output / "manifest.json").write_text(json.dumps({"snapshot_id": doc.id,
                "version": doc.version, "edit_revision": doc.edit_revision,
                "content_hash": digest, "platform": platform, "files": hashes},
                ensure_ascii=False, indent=2), encoding="utf-8")
            # Resolve the current article path only at install time, under the rename lock.
            with library._file_lock:
                root = library.exports_dir(article_id).resolve()
                if not root.is_relative_to(library.library_root().resolve()):
                    raise ValueError("导出路径不在数据目录内")
                root.mkdir(parents=True, exist_ok=True)
                installed = root / platform
                if installed.is_symlink():
                    raise ValueError("导出平台目录不能是符号链接")
                if installed.exists():
                    manifest_path = installed / "manifest.json"
                    if manifest_path.exists():
                        previous = json.loads(manifest_path.read_text(encoding="utf-8"))
                        if (previous.get("version", 0), previous.get("edit_revision", 0)) > (doc.version, doc.edit_revision):
                            raise ValueError("已有更新文稿的导出，请从最新定稿重新生成")
                    installed.rename(backup)
                try:
                    output.rename(installed)
                except BaseException:
                    if backup.exists() and not installed.exists():
                        backup.rename(installed)
                    raise
                res.export_dir = str(installed)
            res.files = list(hashes) + ["manifest.json"]
            dao.finish_publish_job(pid, res.__dict__, ok=True)
            events.bus.publish(events.STAGE_PROGRESS, article_id, stage="publish",
                               message=f"{_PLATFORM_LABEL.get(platform, platform)} 完成：{res.message[:60]}")
        except Exception as e:
            from ... import logging_setup
            logging_setup.log("error", "Export failed article=%s platform=%s", article_id, platform, exc_info=True)
            message = f"导出目录或素材路径不可用：{e}" if isinstance(e, OSError) else str(e)
            dao.finish_publish_job(pid, {"message": message}, ok=False)
            res = PushResult(ok=False, platform=platform, message=message)
        finally:
            # Only task-owned directories underneath the checked stable staging root.
            for temporary in (staging,):
                if temporary.resolve().is_relative_to(staging_root.resolve()):
                    shutil.rmtree(temporary, ignore_errors=True)
            if backup.exists() and res.ok:
                shutil.rmtree(backup, ignore_errors=True)
        results[platform] = res.__dict__
    failed = [p for p, result in results.items() if not result["ok"]]
    status = "SUCCESS" if not failed else "FAILED" if len(failed) == len(results) else "PARTIAL_FAILED"
    return {"article_id": article_id, "snapshot_id": doc.id, "content_hash": digest,
            "export_root": str(library.exports_dir(article_id)), "platforms": results,
            "ok": not failed, "status": status, "failed_platforms": failed}


def _brand_footer_html(badge) -> str:
    """公众号 HTML 末尾的品牌页脚（Logo + 固定文案）。"""
    if not badge:
        return ""
    from .. import brand
    return ("<div style='margin-top:48px;text-align:center;border-top:1px solid #E5E1D8;"
            "padding-top:28px;'><img src='media/logo-badge.png' alt='logo' "
            "style='width:88px;height:88px;border-radius:50%;'>"
            "<p style='color:#8A8577;font-size:14px;letter-spacing:3px;margin-top:12px;'>"
            + brand.SLOGAN + "</p></div>")


def _export_one(doc: DraftDoc, article_id: str, platform: str, root: Path) -> PushResult:
    out = root / platform
    media_dir = out / "media"
    media_dir.mkdir(parents=True, exist_ok=True)
    variant = build_variant(doc, platform)

    files: list[str] = []
    # 媒体拷贝（公众号 HTML 引用 media/ 相对路径）
    for rel in (variant.media if platform != "xhs" else []):
        src = library.material_abs_path(rel)
        if src and src.exists():
            if src.resolve() != (media_dir / src.name).resolve():
                shutil.copy2(src, media_dir / src.name)
            files.append(f"media/{src.name}")

    # 品牌页脚（V1.10）：各平台导出末尾统一 个人 Logo + 固定文案
    from .. import brand
    badge = brand.badge_path()
    if badge and platform == "wechat_mp":
        shutil.copy2(badge, media_dir / "logo-badge.png")
        files.append("media/logo-badge.png")

    label = _PLATFORM_LABEL.get(platform, platform)
    if platform == "wechat_mp":
        (out / "article.html").write_text(
            f"<html><head><meta charset='utf-8'><title>{html.escape(variant.title)}</title>"
            "</head><body style='max-width:677px;margin:0 auto;padding:24px;'>"
            f"{variant.body}{_brand_footer_html(badge)}</body></html>", encoding="utf-8")
        (out / "article.md").write_text(bk.to_markdown(doc), encoding="utf-8")
        files += ["article.html", "article.md"]
        note = ("1. 浏览器打开 article.html，全选复制 → 粘贴进公众号编辑器（样式随行）\n"
                "2. 图片如未随行，从 media/ 目录手动上传替换\n"
                "3. 摘要可填 article.md 开头的一句话总结")
    elif platform == "xhs":
        from ..cards.render import render_cards
        cards = render_cards(article_id, out_dir=out / "cards", doc=doc)
        (out / "caption.txt").write_text(variant.body + "\n\n" + brand.SLOGAN, encoding="utf-8")
        files += [f"cards/{p.name}" for p in cards] + ["caption.txt"]
        note = ("1. cards/ 下 page-01.png 起即为分页卡片（首张为封面），按序上传\n"
                "2. caption.txt 为标题+正文+话题标签，直接复制")
    elif platform == "weibo":
        (out / "weibo.txt").write_text(variant.body, encoding="utf-8")
        files += ["weibo.txt"]
        note = ("复制 weibo.txt（含话题、签名），按 media.json 指示上传图片或单个视频/GIF。\n"
                "文字长度为本软件摘要目标，手动发布和长文能力以当前账号编辑器为准。")
        (out / "media.json").write_text(json.dumps({"media": ["media/" + Path(p).name for p in variant.media],
            "summary_target": variant.extras["summary_target"], "characters": len(variant.body)},
            ensure_ascii=False, indent=2), encoding="utf-8")
        files.append("media.json")
    else:  # x
        (out / "thread.txt").write_text(variant.body, encoding="utf-8")
        files += ["thread.txt"]
        posts = []
        for index, tweet in enumerate(variant.extras["tweets"], 1):
            name = f"post-{index:02d}.txt"
            (out / name).write_text(tweet, encoding="utf-8")
            files.append(name)
            posts.append({"index": index, "file": name, "reply_to_index": index - 1 if index > 1 else None,
                          "weighted_length_upper_bound": weighted_length(tweet),
                          "media": ["media/" + Path(p).name for p in variant.media] if index == 1 else []})
        (out / "thread.json").write_text(json.dumps({"posts": posts,
            "truncated": variant.extras["truncated"], "character_limit": 280},
            ensure_ascii=False, indent=2), encoding="utf-8")
        files.append("thread.json")
        note = ("post-01.txt 起逐条发布；后一条回复上一条，构成 Thread。\n"
                "thread.txt 为合并预览，--- 是分隔符，不要复制进正文。\n"
                "thread.json 指明每条文字与媒体；首条最多4张静态图片，或1个GIF/视频，不混用。\n"
                "普通帖文按280加权字符保守切分（中文通常2，URL 23），发布以编辑器计数为准。")
        if variant.extras["truncated"]:
            note += "\n注意：正文超出当前最大推文条数，已截断；请提高最大条数或人工补充。"

    (out / "README.txt").write_text(
        f"平台: {label}\n标题: {variant.title}\n\n发布步骤:\n{note}\n", encoding="utf-8")
    files.append("README.txt")
    return PushResult(ok=True, platform=platform, export_dir=str(out), files=files,
                      message=f"{label}发布包已生成，请手动到平台发布")
