"""Publisher 插件接口（一阶段仅 exporter 实现；API/RPA 为二阶段扩展点）。"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Protocol

from ...core.models import Variant


@dataclass
class Capabilities:
    draft: bool = False          # 能推送到平台草稿箱
    schedule: bool = False
    media_upload: bool = False
    direct_post: bool = False
    export: bool = True          # 能导出发布包（兜底，永远为 True）


@dataclass
class PushResult:
    ok: bool
    platform: str
    export_dir: str = ""
    remote_ref: str = ""         # 草稿 id / 链接（API 模式）
    message: str = ""
    files: list[str] = field(default_factory=list)


class Publisher(Protocol):
    platform: str

    def capabilities(self) -> Capabilities: ...
    def push(self, article_id: str, doc, out_root) -> PushResult: ...
