"""领域模型（Pydantic）。文档块模型是编辑器的地基，见 docs/design/03。"""
from __future__ import annotations

from enum import Enum
from typing import Any, Literal

from pydantic import BaseModel, Field


class ArticleStatus(str, Enum):
    NEW = "NEW"
    COLLECTING = "COLLECTING"
    COLLECTED = "COLLECTED"
    CREATING = "CREATING"
    DRAFTED = "DRAFTED"
    REVIEWING = "REVIEWING"
    REVIEWED = "REVIEWED"
    EDITING = "EDITING"
    FINALIZED = "FINALIZED"
    PUBLISHING = "PUBLISHING"
    DONE = "DONE"
    FAILED = "FAILED"


UI_STATUS = {
    ArticleStatus.NEW: "New",
    ArticleStatus.COLLECTING: "Process",
    ArticleStatus.COLLECTED: "Process",
    ArticleStatus.CREATING: "Process",
    ArticleStatus.DRAFTED: "Process",
    ArticleStatus.REVIEWING: "Process",
    ArticleStatus.REVIEWED: "Process",
    ArticleStatus.EDITING: "Process",
    ArticleStatus.FINALIZED: "Done",
    ArticleStatus.PUBLISHING: "Done",
    ArticleStatus.DONE: "Done",
    ArticleStatus.FAILED: "Failed",
}


class BlockType(str, Enum):
    HEADING = "heading"
    PARAGRAPH = "paragraph"
    QUOTE = "quote"
    IMAGE = "image"
    VIDEO = "video"
    DIVIDER = "divider"


class Block(BaseModel):
    id: str
    type: BlockType
    level: int = 2                       # heading 专用
    text: str = ""                       # heading/paragraph/quote
    asset_id: str | None = None          # image/video → materials.id
    caption: str | None = None
    source: str | None = None            # 媒体来源说明
    citations: list[str] = Field(default_factory=list)   # 引用素材 id


class XhsPage(BaseModel):
    title: str = ""
    block_ids: list[str] = Field(default_factory=list)
    asset_id: str | None = None


class DraftMeta(BaseModel):
    keywords: list[str] = Field(default_factory=list)
    one_liner: str = ""
    title_candidates: list[str] = Field(default_factory=list)
    subtitle: str = ""                              # 副标题（创作时同步生成）
    ref_links: list[dict] = Field(default_factory=list)  # 参考文字链接 [{title, url}]
    word_count: int = 0
    xhs_pages: list[XhsPage] = Field(default_factory=list)


class DraftDoc(BaseModel):
    id: str
    article_id: str
    version: int
    blocks: list[Block] = Field(default_factory=list)
    meta: DraftMeta = Field(default_factory=DraftMeta)


class MaterialKind(str, Enum):
    TEXT = "text"
    IMAGE = "image"
    VIDEO = "video"
    DOC = "doc"
    LINK = "link"


class RefType(str, Enum):
    PRIMARY = "primary"          # 原文
    REFERENCE = "reference"      # 关联参考
    FOUNDATIONAL = "foundational"  # 窗口外基础资料


Severity = Literal["info", "warn", "blocker"]
ReviewCategory = Literal["layout", "fact", "attribution", "compliance", "originality", "ai_flavor"]


class ChecklistItem(BaseModel):
    id: str
    category: ReviewCategory
    severity: Severity
    block_id: str | None = None
    message: str
    suggestion: str = ""
    evidence: list[str] = Field(default_factory=list)
    auto_fixable: bool = False
    status: Literal["pending", "accepted", "dismissed", "fixed"] = "pending"


class ReviewReport(BaseModel):
    scores: dict[str, Any] = Field(default_factory=dict)
    items: list[ChecklistItem] = Field(default_factory=list)


class CollectionReport(BaseModel):
    topic: str = ""
    keywords: list[str] = Field(default_factory=list)
    core_points: list[str] = Field(default_factory=list)
    entities: list[str] = Field(default_factory=list)
    published_at: str | None = None
    refs: list[dict[str, Any]] = Field(default_factory=list)
    scarce: bool = False
    notes_path: str | None = None


class Variant(BaseModel):
    """平台发布变体（exporter 输出单元）。"""
    platform: str                     # wechat_mp | xhs | weibo | x
    title: str = ""
    body: str = ""                    # 公众号为 HTML，其余为纯文本
    media: list[str] = Field(default_factory=list)   # 素材库相对路径
    extras: dict[str, Any] = Field(default_factory=dict)  # 摘要/话题/分页清单等
